"""Create a new CSV profiling job.

Start a new profiling job by choosing a unique job identifier. The system
generates a random, memorable ID but you can customise it. Once ready,
click "Start" to move on to uploading data and configuring parameters.
"""

import logging

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, html
from dash.exceptions import PreventUpdate

from cosmo_ecosystem.constants import URL_LOCATION_SHARED_ID
from cosmo_ecosystem.db_manager import DbManager
from cosmo_ecosystem.job import Job, find_unique_job_id
from cosmo_ecosystem.layouts import create_header, page_container_column_layout
from cosmo_ecosystem.pydantic_models import validate_job_id

from csv_profiler.constants import (
    JOB_FEEDBACK_FORMTEXT_HOME_ID,
    JOB_INPUT_HOME_ID,
    START_BUTTON_HOME_ID,
)
from csv_profiler.pydantic_models import ProfileConfig

log = logging.getLogger(__name__)

dash.register_page(__name__, path="/")

header = create_header(
    "Welcome to Cosmo-Template",
    "Try it out and create a new job",
    bg_color="bg-info",
)


def layout():
    """Layout for the home page."""
    log.info("Create new job page")
    job_id = find_unique_job_id()

    return page_container_column_layout(
        [
            header,
            dbc.Row(
                dbc.Col(
                    html.Img(
                        src="/static/start_banner.jpg",
                        # no Bootstrap class for specific viewport-relative height
                        style={"height": "45vh"},
                        className="rounded mx-auto d-block m-3",
                        alt="Welcome",
                    ),
                    className="text-center",
                ),
            ),
            dbc.Row(
                dbc.Col(
                    [
                        dbc.Label("Job ID", className="fw-bold"),
                        dbc.Input(
                            id=JOB_INPUT_HOME_ID,
                            value=job_id,
                            html_size=len(job_id) + 10,
                            className="w-auto",
                            type="text",
                        ),
                        dbc.FormText(
                            "",
                            id=JOB_FEEDBACK_FORMTEXT_HOME_ID,
                            className="text-danger",
                        ),
                        html.Br(),
                        dbc.FormText(
                            ProfileConfig.model_fields["job_id"].description,
                        ),
                        html.Br(),
                        html.Div(
                            dbc.Button(
                                [html.I(className="bi bi-gear me-1"), "Start"],
                                id=START_BUTTON_HOME_ID,
                                color="primary",
                            ),
                            className="m-2 d-flex justify-content-center",
                        ),
                    ],
                    width="auto",
                    className="my-4",
                ),
                justify="center",
            ),
        ]
    )


# ============================================================================
# Callbacks
# ============================================================================


@callback(
    Output(URL_LOCATION_SHARED_ID, "pathname", allow_duplicate=True),
    Input(START_BUTTON_HOME_ID, "n_clicks"),
    State(JOB_INPUT_HOME_ID, "value"),
    prevent_initial_call=True,
)
def start_job(n_clicks, job_id):
    """Create the job and navigate to input page."""
    if n_clicks is None:
        raise PreventUpdate
    Job(new_job_id=job_id)
    base_path = dash.page_registry["pages.input"]["path_template"]
    return base_path.replace("<job_id>", str(job_id))


@callback(
    Output(JOB_FEEDBACK_FORMTEXT_HOME_ID, "children"),
    Output(JOB_INPUT_HOME_ID, "valid"),
    Output(JOB_INPUT_HOME_ID, "invalid"),
    Input(JOB_INPUT_HOME_ID, "value"),
    prevent_initial_call=True,
)
def validate_new_job_id(job_id):
    """Validate the job ID in real time."""
    try:
        validate_job_id(job_id)
    except ValueError as e:
        return str(e), False, True

    if DbManager.check_existence(job_id):
        return "Job ID already exists", False, True

    return "", True, False
