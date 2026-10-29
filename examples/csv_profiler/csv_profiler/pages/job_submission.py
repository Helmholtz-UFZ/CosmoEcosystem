"""Submit job and monitor progress.

Review configured parameters, submit the job for background processing,
and monitor status with live log updates. Navigate to results when complete.
Reached via /job-submission/<job_id>.
"""

import logging

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, callback_context, dcc, html
from dash_form_factory import FormFactory

from cosmo_ecosystem.constants import (
    LOADING_OVERLAY_MODAL_SHARED_ID,
    URL_LOCATION_SHARED_ID,
)
from cosmo_ecosystem.error_handling import InvalidJobID, JobNotFound
from cosmo_ecosystem.files_route import create_download_button
from cosmo_ecosystem.job import Job
from cosmo_ecosystem.layouts import (
    job_not_found_layout,
    landing_page_layout_column,
)

from csv_profiler.constants import (
    ACCORDION_JOB_SUBMISSION_ID,
    CHANGE_INPUT_BUTTON_JOB_SUBMISSION_ID,
    HEADER_DIV_JOB_SUBMISSION_ID,
    ICON_JOB_SUBMISSION_ID,
    INTERVAL_JOB_SUBMISSION_ID,
    JOB_LOGS_DIV_JOB_SUBMISSION_ID,
    JOB_STORE_JOB_SUBMISSION_ID,
    MAIN_CONTENT_DIV_JOB_SUBMISSION_ID,
    RESET_JOB_STORE_SHARED_ID,
    RESUBMIT_BUTTON_JOB_SUBMISSION_ID,
    STATUS_DIV_JOB_SUBMISSION_ID,
    SUBMIT_BUTTON_JOB_SUBMISSION_ID,
    VIEW_RESULTS_BUTTON_JOB_SUBMISSION_ID,
)
from csv_profiler.forms import form_layout_template
from csv_profiler.layouts import create_job_header

log = logging.getLogger(__name__)

dash.register_page(
    __name__,
    path_template="/job-submission/<job_id>",
)


status_button_config = {
    "PENDING": {
        "disabled_submit": False,
        "disabled_change_input": False,
        "disabled_resubmit": True,
        "disabled_results": True,
    },
    "RUNNING": {
        "disabled_submit": True,
        "disabled_change_input": True,
        "disabled_resubmit": True,
        "disabled_results": True,
    },
    "FAILED": {
        "disabled_submit": False,
        "disabled_change_input": False,
        "disabled_resubmit": False,
        "disabled_results": True,
    },
    "COMPLETED": {
        "disabled_submit": True,
        "disabled_change_input": False,
        "disabled_resubmit": False,
        "disabled_results": False,
    },
}


def _wrap_button(button):
    """Wrap a button in a row and column for layout."""
    return dbc.Row(
        dbc.Col(
            button,
            className="m-2 d-flex justify-content-center align-items-center",
        ),
    )


def _create_button_set(status, job_id):
    """Create action buttons based on job status."""
    cfg = status_button_config[status]

    submit_button = _wrap_button(
        dbc.Button(
            [html.I(className="bi bi-play-fill me-1"), "Submit Job"],
            id=SUBMIT_BUTTON_JOB_SUBMISSION_ID,
            color="primary",
            disabled=cfg["disabled_submit"],
        )
    )
    change_input_button = _wrap_button(
        dbc.Button(
            [html.I(className="bi bi-pencil-square me-1"), "Change Input"],
            id=CHANGE_INPUT_BUTTON_JOB_SUBMISSION_ID,
            color="primary",
            disabled=cfg["disabled_change_input"],
        )
    )
    resubmit_button = _wrap_button(
        dbc.Button(
            [html.I(className="bi bi-arrow-repeat me-1"), "Resubmit"],
            id=RESUBMIT_BUTTON_JOB_SUBMISSION_ID,
            color="warning",
            disabled=cfg["disabled_resubmit"],
        )
    )
    results_button = _wrap_button(
        dbc.Button(
            [html.I(className="bi bi-bar-chart-line me-1"), "View Results"],
            id=VIEW_RESULTS_BUTTON_JOB_SUBMISSION_ID,
            color="success",
            disabled=cfg["disabled_results"],
        )
    )
    download_button = _wrap_button(create_download_button(job_id, class_name=""))

    return [
        submit_button,
        change_input_button,
        resubmit_button,
        results_button,
        download_button,
    ]


deletion_info_template = "The job will be deleted after {time_to_live} days."
status_info_template = "Status:\n {status}"


def layout(job_id):
    """Layout for the submission page."""
    return landing_page_layout_column(
        "Job Submission",
        HEADER_DIV_JOB_SUBMISSION_ID,
        JOB_STORE_JOB_SUBMISSION_ID,
        job_id,
        MAIN_CONTENT_DIV_JOB_SUBMISSION_ID,
    )


@callback(
    Output(HEADER_DIV_JOB_SUBMISSION_ID, "children"),
    Output(MAIN_CONTENT_DIV_JOB_SUBMISSION_ID, "children"),
    Input(JOB_STORE_JOB_SUBMISSION_ID, "data"),
    prevent_initial_call=False,
)
def load_submission_content(job_id):
    """Load submission page content with input summary, buttons, and logs."""
    try:
        job = Job(job_id=job_id)
    except (InvalidJobID, JobNotFound) as e:
        log.info(f"Job not accessible {job_id}: {e}")
        return job_not_found_layout(job_id)
    job.reload_logs()

    # Read-only form showing configured parameters
    read_only_factory = FormFactory(job.model, form_layout_template, active=False)
    form = read_only_factory.process_layout(read_only_factory.layout)

    # Determine icon and active accordion item
    icon_color = "icon-error" if job.status == "FAILED" else "icon-none"
    active_item = "input_accordion" if job.status == "PENDING" else "logs_accordion"

    accordion_item_style = {
        "max-height": "70vh",
        "overflow-y": "auto",
    }

    accordion = dbc.Accordion(
        [
            dbc.AccordionItem(
                form,
                title="Input",
                item_id="input_accordion",
                style=accordion_item_style,
            ),
            dbc.AccordionItem(
                [
                    html.Div(
                        job.logs,
                        id=JOB_LOGS_DIV_JOB_SUBMISSION_ID,
                        className="w-100 bg-dark text-white p-3 rounded font-monospace",
                        # no Bootstrap class for white-space: pre-wrap
                        style={"white-space": "pre-wrap"},
                    ),
                ],
                title=html.Span(
                    [
                        "Logs",
                        html.I(
                            className=f"bi bi-x-octagon-fill ms-2 {icon_color}",
                            id=ICON_JOB_SUBMISSION_ID,
                        ),
                    ]
                ),
                item_id="logs_accordion",
                style=accordion_item_style,
            ),
        ],
        id=ACCORDION_JOB_SUBMISSION_ID,
        active_item=active_item,
    )

    submission_layout = [accordion]
    submission_layout += _create_button_set(job.status, job.job_id)

    disable_interval = job.status != "RUNNING"

    main_content = html.Div(
        [
            dcc.Interval(
                id=INTERVAL_JOB_SUBMISSION_ID,
                interval=3000,
                disabled=disable_interval,
            ),
            html.Div(
                status_info_template.format(status=job.status),
                id=STATUS_DIV_JOB_SUBMISSION_ID,
                className="text-center fs-4",
                # no Bootstrap class for white-space: pre-line
                style={"white-space": "pre-line"},
            ),
            html.Div(
                deletion_info_template.format(time_to_live=job.time_to_live()),
                className="text-center fs-5 mb-2",
            ),
            dbc.Row(
                dbc.Col(
                    submission_layout,
                    className="col-11 col-xl-8 mx-auto",
                )
            ),
        ]
    )

    return create_job_header("Job Submission", job), main_content


@callback(
    Output(LOADING_OVERLAY_MODAL_SHARED_ID, "is_open", allow_duplicate=True),
    Input(SUBMIT_BUTTON_JOB_SUBMISSION_ID, "n_clicks"),
    Input(CHANGE_INPUT_BUTTON_JOB_SUBMISSION_ID, "n_clicks"),
    Input(RESUBMIT_BUTTON_JOB_SUBMISSION_ID, "n_clicks"),
    Input(VIEW_RESULTS_BUTTON_JOB_SUBMISSION_ID, "n_clicks"),
    prevent_initial_call=True,
)
def open_loading_overlay(*args):
    """Open the loading overlay when any action button is clicked.

    A clientside_callback would eliminate the race condition between this
    callback and the processing callback (both target LOADING_OVERLAY via
    allow_duplicate). Server-side is used here for consistency — the project
    avoids JS. If the overlay flickers or gets stuck, switch to clientside.
    """
    if all(v is None for v in args):
        return dash.no_update
    return True


@callback(
    Output(URL_LOCATION_SHARED_ID, "pathname", allow_duplicate=True),
    Output(LOADING_OVERLAY_MODAL_SHARED_ID, "is_open", allow_duplicate=True),
    Output(JOB_LOGS_DIV_JOB_SUBMISSION_ID, "children"),
    Output(INTERVAL_JOB_SUBMISSION_ID, "disabled", allow_duplicate=True),
    Output(ICON_JOB_SUBMISSION_ID, "className"),
    Output(SUBMIT_BUTTON_JOB_SUBMISSION_ID, "disabled"),
    Output(CHANGE_INPUT_BUTTON_JOB_SUBMISSION_ID, "disabled"),
    Output(RESUBMIT_BUTTON_JOB_SUBMISSION_ID, "disabled"),
    Output(VIEW_RESULTS_BUTTON_JOB_SUBMISSION_ID, "disabled"),
    Output(STATUS_DIV_JOB_SUBMISSION_ID, "children"),
    Output(ACCORDION_JOB_SUBMISSION_ID, "active_item"),
    Output(HEADER_DIV_JOB_SUBMISSION_ID, "children", allow_duplicate=True),
    Output(RESET_JOB_STORE_SHARED_ID, "data", allow_duplicate=True),
    Input(INTERVAL_JOB_SUBMISSION_ID, "n_intervals"),
    Input(SUBMIT_BUTTON_JOB_SUBMISSION_ID, "n_clicks"),
    Input(CHANGE_INPUT_BUTTON_JOB_SUBMISSION_ID, "n_clicks"),
    Input(RESUBMIT_BUTTON_JOB_SUBMISSION_ID, "n_clicks"),
    Input(VIEW_RESULTS_BUTTON_JOB_SUBMISSION_ID, "n_clicks"),
    State(JOB_STORE_JOB_SUBMISSION_ID, "data"),
    prevent_initial_call=True,
)
def submission_manager(
    n_intervals,
    clicks_submit,
    clicks_change_input,
    clicks_resubmit,
    clicks_results,
    job_id,
):
    """Handle submit, navigation, and live log polling."""
    log.info(f"Submission manager for {job_id}")
    triggered_ids = {
        t["prop_id"].split(".")[0]
        for t in callback_context.triggered
        if t["value"] is not None
    }
    num_outputs = len(dash.callback_context.outputs_list)
    log.debug(f"Triggered ids: {triggered_ids}")

    job = Job(job_id=job_id)

    # Handle button actions
    if SUBMIT_BUTTON_JOB_SUBMISSION_ID in triggered_ids:
        job.delete_logs()
        job.submit()
    elif RESUBMIT_BUTTON_JOB_SUBMISSION_ID in triggered_ids:
        # Trigger confirmation modal
        return tuple(
            [dash.no_update, False]
            + [dash.no_update] * (num_outputs - 3)
            + [{"job_id": job.job_id, "action": "resubmit"}]
        )
    elif CHANGE_INPUT_BUTTON_JOB_SUBMISSION_ID in triggered_ids:
        if job.status == "PENDING":
            input_base = dash.page_registry["pages.input"]["path_template"]
            input_path = input_base.replace("<job_id>", job.job_id)
            return tuple([input_path] + [dash.no_update] * (num_outputs - 1))
        # Non-PENDING: trigger confirmation modal
        return tuple(
            [dash.no_update, False]
            + [dash.no_update] * (num_outputs - 3)
            + [{"job_id": job.job_id, "action": "change_input"}]
        )
    elif VIEW_RESULTS_BUTTON_JOB_SUBMISSION_ID in triggered_ids:
        results_base = dash.page_registry["pages.results"]["path_template"]
        results_path = results_base.replace("<job_id>", job.job_id)
        return tuple([results_path] + [dash.no_update] * (num_outputs - 1))

    # Refresh state
    job.reload_logs()
    url = dash.no_update
    show_loading = False
    disable_interval = job.status != "RUNNING"
    icon_color = "icon-error" if job.status == "FAILED" else "icon-none"
    cfg = status_button_config[job.status]
    status_info = status_info_template.format(status=job.status)
    active_item = "input_accordion" if job.status == "PENDING" else "logs_accordion"

    return (
        url,
        show_loading,
        job.logs,
        disable_interval,
        icon_color,
        cfg["disabled_submit"],
        cfg["disabled_change_input"],
        cfg["disabled_resubmit"],
        cfg["disabled_results"],
        status_info,
        active_item,
        create_job_header("Job Submission", job),
        dash.no_update,
    )
