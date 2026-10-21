"""Manage all jobs from a central dashboard.

This administrative page provides a comprehensive overview of all jobs in the system.
You can:
- View all jobs in a sortable, filterable table
- See job status, creation dates, and submission status at a glance
- Select and delete individual jobs or multiple jobs at once
- Trigger cleanup operations to remove old jobs automatically
"""

import logging
import re
from datetime import datetime

import dash
import dash_ag_grid as dag
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, dcc, html

from cosmo_ecosystem.constants import (
    CLEAN_BUTTON_JOB_MANAGEMENT_ID,
    DELETE_BUTTON_JOB_MANAGEMENT_ID,
    DUMMY_STORE_JOB_MANAGEMENT_ID,
    JOBS_TABLE_JOB_MANAGEMENT_ID,
    LOADING_OVERLAY_MODAL_SHARED_ID,
    REFRESH_BUTTON_JOB_MANAGEMENT_ID,
)
from cosmo_ecosystem.job_retention import clean_up_jobs, delete_job
from cosmo_ecosystem.layouts import create_header, page_container_column_layout
from cosmo_ecosystem.db_manager import DbManager

log = logging.getLogger(__name__)


table = dag.AgGrid(
    id=JOBS_TABLE_JOB_MANAGEMENT_ID,
    columnDefs=[
        {
            "field": "job_id",
            "headerName": "Job ID",
            "cellRenderer": "markdown",
            "cellStyle": {"textAlign": "left", "fontFamily": "monospace"},
        },
        {
            "field": "status",
            "headerName": "Status",
            "cellStyle": {
                "styleConditions": [
                    {
                        "condition": "params.value === 'COMPLETED'",
                        "style": {"backgroundColor": "#3498db"},
                    },
                    {
                        "condition": "params.value === 'RUNNING'",
                        "style": {"backgroundColor": "#2ecc71"},
                    },
                    {
                        "condition": "params.value === 'FAILED'",
                        "style": {"backgroundColor": "#e74c3c"},
                    },
                    {
                        "condition": "params.value === 'PENDING'",
                        "style": {"backgroundColor": "#f39c12"},
                    },
                ],
            },
        },
        {"field": "start_date", "headerName": "Start Date"},
        {"field": "submitted", "headerName": "Submitted"},
    ],
    rowData=[],
    defaultColDef={"cellStyle": {"textAlign": "center"}},
    dashGridOptions={
        "rowSelection": {"mode": "multiRow"},
        "suppressCellFocus": True,
    },
    columnSize="responsiveSizeToFit",
)

button_group = [
    dbc.Button(
        [html.I(className="bi bi-arrow-clockwise me-1"), "Refresh Jobs"],
        id=REFRESH_BUTTON_JOB_MANAGEMENT_ID,
        color="primary",
        className="ms-2 float-end",
    ),
    dbc.Button(
        [html.I(className="bi bi-trash me-1"), "Delete Selection"],
        id=DELETE_BUTTON_JOB_MANAGEMENT_ID,
        color="danger",
        className="ms-2 float-end",
    ),
    dbc.Button(
        [html.I(className="bi bi-recycle me-1"), "Clean"],
        id=CLEAN_BUTTON_JOB_MANAGEMENT_ID,
        color="warning",
        className="ms-2 float-end",
    ),
]

layout = page_container_column_layout(
    [
        create_header(
            "Job Management",
            "Overview and management of jobs",
            bg_color="bg-info",
        ),
        dcc.Store(id=DUMMY_STORE_JOB_MANAGEMENT_ID, data=None),
        dbc.Row(
            dbc.Col(
                button_group,
            ),
            className="m-2",
        ),
        dbc.Row(
            dbc.Col(
                table,
            ),
            className="m-2",
        ),
    ]
)


@callback(
    Output(LOADING_OVERLAY_MODAL_SHARED_ID, "is_open", allow_duplicate=True),
    Input(DELETE_BUTTON_JOB_MANAGEMENT_ID, "n_clicks"),
    Input(CLEAN_BUTTON_JOB_MANAGEMENT_ID, "n_clicks"),
    Input(REFRESH_BUTTON_JOB_MANAGEMENT_ID, "n_clicks"),
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
    Output(JOBS_TABLE_JOB_MANAGEMENT_ID, "rowData"),
    Output(JOBS_TABLE_JOB_MANAGEMENT_ID, "selectedRows"),
    Output(LOADING_OVERLAY_MODAL_SHARED_ID, "is_open", allow_duplicate=True),
    Input(DELETE_BUTTON_JOB_MANAGEMENT_ID, "n_clicks"),
    Input(CLEAN_BUTTON_JOB_MANAGEMENT_ID, "n_clicks"),
    Input(REFRESH_BUTTON_JOB_MANAGEMENT_ID, "n_clicks"),
    Input(DUMMY_STORE_JOB_MANAGEMENT_ID, "data"),
    State(JOBS_TABLE_JOB_MANAGEMENT_ID, "selectedRows"),
    prevent_initial_call=True,
)
def job_management_dashboard(
    delete_clicks, clean_clicks, refresh_clicks, _dummy, selected_rows
):
    """Manage job actions in the dashboard."""
    log.info("Job management dashboard callback triggered.")
    button_id = dash.callback_context.triggered[0]["prop_id"].split(".")[0]

    if button_id == DELETE_BUTTON_JOB_MANAGEMENT_ID and selected_rows:
        log.info("Deleting selected jobs")
        for row in selected_rows:
            job_id = re.findall(r"\[(.*?)\]", row["job_id"])[0]
            log.debug(f"Deleting job with ID: {job_id}")
            delete_job(job_id)
    elif button_id == CLEAN_BUTTON_JOB_MANAGEMENT_ID:
        log.info("Cleaning unsubmitted jobs")
        clean_up_jobs(days_delete_not_submitted=0)

    jobs_dict = DbManager.list_jobs()

    rows = []
    for job_id, job_data in jobs_dict.items():
        start_date = (
            job_data["start_date"].strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(job_data["start_date"], datetime)
            else job_data["start_date"]
        )

        # Link to job submission page for all jobs
        job_id_markdown = f"[{job_id}](/job-submission/{job_id})"

        rows.append(
            {
                "job_id": job_id_markdown,
                "status": job_data["status"],
                "start_date": start_date,
                "submitted": "Yes" if job_data["submitted"] else "No",
            }
        )

    if button_id in [DELETE_BUTTON_JOB_MANAGEMENT_ID, CLEAN_BUTTON_JOB_MANAGEMENT_ID]:
        return rows, [], False
    return rows, dash.no_update, False


# Registered with an explicit "pages.*" key + layout so an app can import this
# framework page across the package boundary (not via local pages_folder discovery).
dash.register_page(
    "pages.job_management",
    layout=layout,
)
