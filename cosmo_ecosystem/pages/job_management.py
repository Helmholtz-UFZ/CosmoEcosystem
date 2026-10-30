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
from dash import Input, Output, State, callback, callback_context, dcc, html

from cosmo_ecosystem.constants import (
    CLEAN_BUTTON_JOB_MANAGEMENT_ID,
    DELETE_BUTTON_JOB_MANAGEMENT_ID,
    DUMMY_STORE_JOB_MANAGEMENT_ID,
    JOBS_TABLE_JOB_MANAGEMENT_ID,
    LOADING_OVERLAY_MODAL_SHARED_ID,
    REFRESH_BUTTON_JOB_MANAGEMENT_ID,
)
from cosmo_ecosystem import pages
from cosmo_ecosystem.error_handling import JobLinkNotConfigured
from cosmo_ecosystem.job_persistence import delete_jobs
from cosmo_ecosystem.job_retention import clean_up_jobs
from cosmo_ecosystem.layouts import create_header, page_container_column_layout
from cosmo_ecosystem.db_manager import DbManager

log = logging.getLogger(__name__)

# The row link is the one thing the apps disagree on, so it is a seam with no
# default (see `cosmo_ecosystem/pages/__init__.py`). Checked here, at import,
# because a missing link would otherwise only show as dead links in the table.
if pages.job_link is None:
    raise JobLinkNotConfigured()


# Inline CSS on purpose (CLAUDE.md, "Convention Philosophy"): the status colours
# are the same in every consuming app, and the apps' user docs name them.
# Bootstrap classes would take each app's theme colours instead.
STATUS_CELL_STYLE = {
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
}

table = dag.AgGrid(
    id=JOBS_TABLE_JOB_MANAGEMENT_ID,
    columnDefs=[
        {
            "field": "job_id",
            "headerName": "Job ID",
            "cellRenderer": "markdown",
            "cellClass": "text-start font-monospace",
        },
        {
            "field": "status",
            "headerName": "Status",
            "cellStyle": STATUS_CELL_STYLE,
        },
        {"field": "start_date", "headerName": "Start Date"},
        {"field": "submitted", "headerName": "Submitted"},
    ],
    rowData=[],
    defaultColDef={"cellClass": "text-center"},
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


def build_rows(jobs):
    """Turn ``DbManager.list_jobs()`` into AG Grid rows.

    The job id links to wherever the app's ``pages.job_link`` says; it gets the
    full row so the link can depend on any column. Read through the package at
    call time, never bound at import, so the seam stays a seam.
    """
    rows = []
    for job_id, job_data in jobs.items():
        start_date = (
            job_data["start_date"].strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(job_data["start_date"], datetime)
            else job_data["start_date"]
        )
        rows.append(
            {
                "job_id": f"[{job_id}]({pages.job_link(job_id, job_data)})",
                "status": job_data["status"],
                "start_date": start_date,
                "submitted": "Yes" if job_data["submitted"] else "No",
            }
        )
    return rows


# Clientside, as docs/conventions/callbacks.md requires: it runs in the browser
# before the server roundtrip starts. A server-side opener can land after the
# processing callback has closed the overlay (both write it via allow_duplicate)
# and leave it stuck open. Inputs are the three buttons only, not the dummy store:
# the store should not show the overlay, and identical inputs would give both
# callbacks the same allow_duplicate id.
dash.clientside_callback(
    """
    function() {
        for (var i = 0; i < arguments.length; i++) {
            if (arguments[i] != null) return true;
        }
        return false;
    }
    """,
    Output(LOADING_OVERLAY_MODAL_SHARED_ID, "is_open", allow_duplicate=True),
    Input(DELETE_BUTTON_JOB_MANAGEMENT_ID, "n_clicks"),
    Input(CLEAN_BUTTON_JOB_MANAGEMENT_ID, "n_clicks"),
    Input(REFRESH_BUTTON_JOB_MANAGEMENT_ID, "n_clicks"),
    prevent_initial_call=True,
)


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
    # A set, not triggered[0]: Dash may batch several inputs into one call
    # (callbacks.md, "Identifying the Trigger").
    triggered_ids = {
        t["prop_id"].split(".")[0]
        for t in callback_context.triggered
        if t["value"] is not None
    }

    if DELETE_BUTTON_JOB_MANAGEMENT_ID in triggered_ids and selected_rows:
        log.info("Deleting selected jobs")
        delete_jobs(
            [re.findall(r"\[(.*?)\]", row["job_id"])[0] for row in selected_rows]
        )
    if CLEAN_BUTTON_JOB_MANAGEMENT_ID in triggered_ids:
        log.info("Cleaning unsubmitted jobs")
        clean_up_jobs(days_delete_not_submitted=0)

    rows = build_rows(DbManager.list_jobs())

    if triggered_ids & {
        DELETE_BUTTON_JOB_MANAGEMENT_ID,
        CLEAN_BUTTON_JOB_MANAGEMENT_ID,
    }:
        return rows, [], False
    return rows, dash.no_update, False


# Registered with an explicit "pages.*" key + layout so an app can import this
# framework page across the package boundary (not via local pages_folder discovery).
dash.register_page(
    "pages.job_management",
    layout=layout,
)
