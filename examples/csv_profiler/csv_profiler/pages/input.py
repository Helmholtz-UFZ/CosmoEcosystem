"""Upload CSV and configure profiling parameters.

Upload a CSV file, set profiling options via the auto-generated form, and
proceed to submission when everything validates. Reached via /input/<job_id>.
"""

import logging

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, callback_context, dcc, html
from dash_form_factory import FormFactory
from cosmo_ecosystem.constants import (
    RESET_JOB_STORE_SHARED_ID,
    URL_LOCATION_SHARED_ID,
)
from cosmo_ecosystem.error_handling import (
    FileValidationError,
    InvalidJobID,
    JobNotFound,
)
from cosmo_ecosystem.job import Job
from cosmo_ecosystem.layouts import (
    create_job_header,
    job_not_found_layout,
    landing_page_layout_column,
)

from csv_profiler.constants import (
    CHECK_INPUT_BUTTON_INPUT_ID,
    CSV_UPLOAD_INPUT_ID,
    FORM_VALID_STORE_INPUT_ID,
    HEADER_DIV_INPUT_ID,
    JOB_STORE_INPUT_ID,
    MAIN_CONTENT_DIV_INPUT_ID,
    RESET_JOB_BUTTON_INPUT_ID,
    UPLOAD_FEEDBACK_DIV_INPUT_ID,
    UPLOADED_FILE_NAME_STORE_INPUT_ID,
)
from csv_profiler.forms import form_factory, form_layout_template

log = logging.getLogger(__name__)

dash.register_page(
    __name__,
    path_template="/input/<job_id>",
)

upload_component = dcc.Upload(
    id=CSV_UPLOAD_INPUT_ID,
    children=dbc.Card(
        dbc.CardBody(
            [
                html.I(className="bi bi-cloud-arrow-up fs-1"),
                html.P(
                    "Drag & drop or click to select a CSV file",
                    className="mt-2 mb-0",
                ),
            ],
            className="text-center py-4",
        ),
        className="border border-2 border-secondary",
    ),
    multiple=False,
)


def layout(job_id):
    """Layout for the input page."""
    return landing_page_layout_column(
        "Input",
        HEADER_DIV_INPUT_ID,
        JOB_STORE_INPUT_ID,
        job_id,
        MAIN_CONTENT_DIV_INPUT_ID,
    )


@callback(
    Output(HEADER_DIV_INPUT_ID, "children"),
    Output(MAIN_CONTENT_DIV_INPUT_ID, "children"),
    Input(JOB_STORE_INPUT_ID, "data"),
    prevent_initial_call=False,
)
def load_input_content(job_id):
    """Load the input page content after job store is populated."""
    try:
        job = Job(job_id=job_id)
    except (InvalidJobID, JobNotFound) as e:
        log.info(f"Job not accessible {job_id}: {e}")
        return job_not_found_layout(job_id)

    if job.status == "PENDING":
        content = _build_editable_content(job)
    else:
        content = _build_readonly_content(job)

    return create_job_header("Input", job), content


def _build_editable_content(job):
    """Build editable input form pre-populated with job values."""
    active_factory = FormFactory(job.model, form_layout_template)
    form = active_factory.process_layout(active_factory.layout)

    if job.model.upload_file_name is not None:
        upload_data = {
            "file_name": job.model.upload_file_name,
            "valid": True,
            "message": (
                f"File uploaded: {job.model.upload_file_name}."
                " To change the file, upload a new one."
            ),
        }
    else:
        upload_data = None

    return html.Div(
        [
            dcc.Store(id=FORM_VALID_STORE_INPUT_ID, data=False),
            dcc.Store(id=UPLOADED_FILE_NAME_STORE_INPUT_ID, data=upload_data),
            dbc.Row(dbc.Col(upload_component), className="m-3"),
            html.Div(id=UPLOAD_FEEDBACK_DIV_INPUT_ID, className="mx-3"),
            dbc.Row(dbc.Col(form), className="m-3"),
            dbc.Row(
                dbc.Col(
                    dbc.Button(
                        [
                            html.I(className="bi bi-check-circle me-1"),
                            "Check Input",
                        ],
                        id=CHECK_INPUT_BUTTON_INPUT_ID,
                        color="primary",
                        disabled=True,
                    ),
                    className="text-center",
                ),
                className="m-3",
            ),
        ],
    )


def _build_readonly_content(job):
    """Build read-only view for non-PENDING jobs with info badge."""
    readonly_factory = FormFactory(job.model, form_layout_template, active=False)
    form = readonly_factory.process_layout(readonly_factory.layout)

    if job.status == "RUNNING":
        badge_text = "Job is currently running."
    else:
        badge_text = "Job must be reset before editing inputs."

    parts = [
        dbc.Alert(badge_text, color="info", className="text-center m-3"),
    ]

    if job.model.upload_file_name:
        parts.append(
            dbc.Alert(
                f"File: {job.model.upload_file_name}",
                color="secondary",
                className="mx-3",
            )
        )

    parts.append(dbc.Row(dbc.Col(form), className="m-3"))

    if job.status != "RUNNING":
        parts.append(
            dbc.Row(
                dbc.Col(
                    dbc.Button(
                        [
                            html.I(className="bi bi-arrow-repeat me-1"),
                            "Reset Job",
                        ],
                        id=RESET_JOB_BUTTON_INPUT_ID,
                        color="warning",
                    ),
                    className="text-center",
                ),
                className="m-3",
            )
        )

    return html.Div(parts)


@callback(
    Output(UPLOADED_FILE_NAME_STORE_INPUT_ID, "data"),
    Input(CSV_UPLOAD_INPUT_ID, "contents"),
    State(CSV_UPLOAD_INPUT_ID, "filename"),
    State(JOB_STORE_INPUT_ID, "data"),
    prevent_initial_call=True,
)
def handle_upload(contents, filename, job_id):
    """Sanitize, validate, and save uploaded CSV via Job.upload_file().

    Writes a dict to the upload store: {file_name, valid, message}.
    update_feedback is the single owner of the feedback div and reads
    this store to render the appropriate alert.
    """
    if contents is None:
        return dash.no_update

    log.info(f"File uploaded: {filename}")

    content_type, content_string = contents.split(",")
    job = Job(job_id=job_id)

    try:
        safe_name = job.upload_file(content_type, content_string, filename)
    except FileValidationError as e:
        log.warning(f"Upload validation failed for job {job_id}: {e}")
        return {"file_name": None, "valid": False, "message": str(e)}

    log.info(f"CSV saved for job {job_id}: {safe_name}")
    return {
        "file_name": safe_name,
        "valid": True,
        "message": f"File uploaded: {safe_name}. To change the file, upload a new one.",
    }


@callback(
    Output(UPLOAD_FEEDBACK_DIV_INPUT_ID, "children"),
    Output(CHECK_INPUT_BUTTON_INPUT_ID, "disabled"),
    Input(FORM_VALID_STORE_INPUT_ID, "data"),
    Input(UPLOADED_FILE_NAME_STORE_INPUT_ID, "data"),
    prevent_initial_call=True,
)
def update_feedback(form_valid, upload_data):
    """Update feedback alert and Check Input button based on form/upload state.

    upload_data is a dict {file_name, valid, message} or None.
    """
    has_file = upload_data is not None and upload_data["valid"]
    upload_failed = upload_data is not None and not upload_data["valid"]
    both_ready = form_valid and has_file

    if upload_failed:
        feedback = dbc.Alert(
            f"Upload failed: {upload_data['message']}",
            color="danger",
            className="mb-0",
        )
    elif not form_valid and not has_file:
        feedback = dbc.Alert(
            "Upload a CSV file and fix form errors.",
            color="danger",
            className="mb-0",
        )
    elif not has_file:
        feedback = dbc.Alert(
            "Upload a CSV file.",
            color="warning",
            className="mb-0",
        )
    elif not form_valid:
        feedback = dbc.Alert(
            [
                html.I(className="bi bi-check-circle me-1"),
                f" {upload_data['message']} Fix form errors.",
            ],
            color="warning",
            className="mb-0",
        )
    else:
        feedback = dbc.Alert(
            [
                html.I(className="bi bi-check-circle me-1"),
                f" {upload_data['message']} Ready to submit.",
            ],
            color="success",
            className="mb-0",
        )

    return feedback, not both_ready


@callback(
    output={
        **form_factory.produce_callback_outputs(),
        "form_valid": Output(FORM_VALID_STORE_INPUT_ID, "data"),
        "redirect": Output(URL_LOCATION_SHARED_ID, "pathname"),
    },
    inputs={
        **form_factory.produce_callback_inputs(),
        "check": Input(CHECK_INPUT_BUTTON_INPUT_ID, "n_clicks"),
    },
    state={
        "job_id": State(JOB_STORE_INPUT_ID, "data"),
        "uploaded_file_name": State(UPLOADED_FILE_NAME_STORE_INPUT_ID, "data"),
    },
    prevent_initial_call="initial_duplicate",
)
def check_input(**inputs):
    """Validate form inputs; on Check Input click, save config and navigate."""
    triggered_ids = {
        t["prop_id"].split(".")[0]
        for t in callback_context.triggered
        if t["value"] is not None
    }

    valid, output_dict = form_factory.validate_callback(inputs)
    output_dict["form_valid"] = valid
    output_dict["redirect"] = dash.no_update

    if CHECK_INPUT_BUTTON_INPUT_ID in triggered_ids and valid:
        job_id = inputs["job_id"]
        model = form_factory.set_model(inputs)
        model.job_id = job_id
        model.upload_file_name = inputs["uploaded_file_name"]["file_name"]
        job = Job(job_id=job_id)
        job.model = model
        job.dump_parameters()
        job.save()
        log.info(f"Input validated for job {job_id}")

        submission_base = dash.page_registry["pages.job_submission"]["path_template"]
        output_dict["redirect"] = submission_base.replace("<job_id>", str(job_id))

    return output_dict


@callback(
    Output(RESET_JOB_STORE_SHARED_ID, "data", allow_duplicate=True),
    Input(RESET_JOB_BUTTON_INPUT_ID, "n_clicks"),
    State(JOB_STORE_INPUT_ID, "data"),
    prevent_initial_call=True,
)
def trigger_reset_from_input(n_clicks, job_id):
    """Write to the shared reset store to trigger the confirmation modal."""
    return {"job_id": job_id, "action": "change_input"}
