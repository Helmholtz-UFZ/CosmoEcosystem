"""Worker Management Page.

# User documentation (This section is for user documentation and will appear in the user documentation.)

Monitor and manage background workers and tasks.

This administrative page provides real-time visibility into the Celery background task
system that processes prediction jobs and maintenance operations. Features include:

**Worker Status:**
- View active worker processes and their configuration
- See worker pool types, concurrency settings, and queue assignments
- Check worker availability and health

**Task Monitoring:**
- View currently executing tasks (active tasks)
- See tasks waiting in worker queues (reserved tasks)
- Monitor scheduled tasks waiting for their run time
- Track revoked (cancelled) tasks
- Display task details including name, arguments, and execution time

**Task Control:**
- Kill actively running tasks (forcefully terminate)
- Cancel scheduled tasks before they execute
- Confirmation dialogs prevent accidental terminations

**Status Updates:**
- Manual refresh to get latest worker and task information
- Timestamp showing when data was last refreshed

This page is essential for monitoring system load, debugging stuck tasks, and managing
resource usage during peak periods.

# Notes (This section is for developer notes and will not appear in the user documentation.)

No additional developer notes for this page.
"""

import logging
from datetime import datetime

import dash
import dash_ag_grid as dag
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, html, no_update, register_page
from dash.exceptions import PreventUpdate

from cosmo_ecosystem.background_job_manager import background_job_manager
from cosmo_ecosystem.constants import (
    ACTIVE_TASKS_TABLE_WORKER_MANAGEMENT_ID,
    CANCEL_MODAL_CANCEL_BUTTON_WORKER_MANAGEMENT_ID,
    CANCEL_MODAL_CONFIRM_BUTTON_WORKER_MANAGEMENT_ID,
    CANCEL_MODAL_TASK_INFO_DIV_WORKER_MANAGEMENT_ID,
    CANCEL_MODAL_WORKER_MANAGEMENT_ID,
    KILL_MODAL_CANCEL_BUTTON_WORKER_MANAGEMENT_ID,
    KILL_MODAL_CONFIRM_BUTTON_WORKER_MANAGEMENT_ID,
    KILL_MODAL_TASK_INFO_DIV_WORKER_MANAGEMENT_ID,
    KILL_MODAL_WORKER_MANAGEMENT_ID,
    LOADING_OVERLAY_MODAL_SHARED_ID,
    RESERVED_TASKS_TABLE_WORKER_MANAGEMENT_ID,
    REVOKED_TASKS_TABLE_WORKER_MANAGEMENT_ID,
    SCHEDULED_TASKS_TABLE_WORKER_MANAGEMENT_ID,
    TEST_TASK_BUTTON_WORKER_MANAGEMENT_ID,
    WORKER_CANCEL_BTN_WORKER_MANAGEMENT_ID,
    WORKER_KILL_BTN_WORKER_MANAGEMENT_ID,
    WORKER_LAST_REFRESH_DIV_WORKER_MANAGEMENT_ID,
    WORKER_MANAGEMENT_DUMMY_COMPONENT_WORKER_MANAGEMENT_ID,
    WORKER_REFRESH_BTN_WORKER_MANAGEMENT_ID,
    WORKER_STATS_CARD_DIV_WORKER_MANAGEMENT_ID,
)
from cosmo_ecosystem.layouts import create_header, page_container_column_layout

log = logging.getLogger(__name__)

# Page registration is at the bottom of this file (explicit "pages.*" key + layout).


# ============================================================================
# Factory Functions (Reusable Components)
# ============================================================================


def create_task_datatable(table_id, columns, selectable=False):
    """Create a consistently styled AgGrid for task display.

    Args:
        table_id: HTML ID for the table
        columns: List of column dicts with "id" and "name" keys
        selectable: Whether to enable row selection

    Returns:
        dag.AgGrid: Configured AgGrid component
    """
    column_defs = []
    for col in columns:
        col_def = {"field": col["id"], "headerName": col["name"]}
        if col["id"] == "task_id":
            col_def["cellStyle"] = {"fontFamily": "monospace", "fontSize": "12px"}
        column_defs.append(col_def)

    grid_options = {
        "pagination": True,
        "paginationPageSize": 10,
    }

    if selectable:
        grid_options["rowSelection"] = {"mode": "singleRow"}

    return dag.AgGrid(
        id=table_id,
        columnDefs=column_defs,
        rowData=[],
        defaultColDef={
            "cellStyle": {"textAlign": "left", "padding": "8px"},
            "sortable": True,
            "resizable": True,
        },
        dashGridOptions=grid_options,
        getRowStyle={
            "styleConditions": [
                {
                    "condition": "params.node.rowIndex % 2 !== 0",
                    "style": {"backgroundColor": "#f8f9fa"},
                },
            ],
        },
        columnSize="responsiveSizeToFit",
    )


def create_task_section(
    title,
    description,
    table_id,
    columns,
    button_id=None,
    button_label=None,
    selectable=False,
    initially_disabled=True,
):
    """Create a task section with title, description, table, and optional button.

    Args:
        title: Section title
        description: Section description
        table_id: ID for the AgGrid table
        columns: List of column names
        button_id: Optional button ID
        button_label: Optional button label
        selectable: Whether table rows are selectable
        initially_disabled: Whether button is initially disabled

    Returns:
        dbc.Card: Section component
    """
    table = create_task_datatable(table_id, columns, selectable)

    section_content = [
        html.H4(title, className="mb-2"),
        html.P(description, className="text-muted mb-3"),
        table,
    ]

    if button_id and button_label:
        button = dbc.Button(
            button_label,
            id=button_id,  # nocheck
            color="danger" if "Kill" in button_label else "warning",
            className="mt-3",
            disabled=initially_disabled,
        )
        section_content.append(button)

    return dbc.Card(
        dbc.CardBody(section_content),
        className="mb-4",
    )


# ============================================================================
# Data Formatting Functions
# ============================================================================


def format_duration(start_timestamp):
    """Convert Unix timestamp to human-readable duration.

    Args:
        start_timestamp: Unix timestamp of task start

    Returns:
        str: Duration in format like "2m 30s" or "1h 15m"
    """
    if not start_timestamp:
        return "N/A"

    duration_seconds = int(datetime.now().timestamp() - start_timestamp)
    if duration_seconds < 60:
        return f"{duration_seconds}s"
    elif duration_seconds < 3600:
        minutes = duration_seconds // 60
        seconds = duration_seconds % 60
        return f"{minutes}m {seconds}s"
    else:
        hours = duration_seconds // 3600
        minutes = (duration_seconds % 3600) // 60
        return f"{hours}h {minutes}m"


def format_active_tasks(active_tasks):
    """Format active tasks for display.

    Args:
        active_tasks: List of active task dicts from Celery

    Returns:
        list: Formatted task dicts
    """
    formatted = []
    for task in active_tasks:
        # A task carries its job_id as the first positional arg; framework code
        # cannot know domain task names, so infer job_id from presence of args.
        job_id = str(task["args"][0]) if task["args"] else "N/A"
        formatted.append(
            {
                "task_id": task["id"],
                "task_name": task["name"].split(".")[-1],
                "worker": task["worker"],
                "start_time": (
                    datetime.fromtimestamp(task["time_start"]).strftime("%H:%M:%S")
                    if task.get(
                        "time_start"
                    )  # time_start absent for tasks not yet started
                    else "N/A"
                ),
                "duration": format_duration(task.get("time_start")),  # see above
                "job_id": job_id,
            }
        )
    return formatted


def format_reserved_tasks(reserved_tasks):
    """Format reserved tasks for display.

    Args:
        reserved_tasks: List of reserved task dicts

    Returns:
        list: Formatted task dicts
    """
    formatted = []
    for task in reserved_tasks:
        formatted.append(
            {
                "task_id": task["id"],
                "task_name": task["name"].split(".")[-1],
                # delivery_info may be absent for tasks without routing info
                "queue": task.get("delivery_info", {}).get("routing_key", "default"),
                "worker": task["worker"],
            }
        )
    return formatted


def format_scheduled_tasks(scheduled_tasks):
    """Format scheduled tasks for display.

    Args:
        scheduled_tasks: List of scheduled task dicts

    Returns:
        list: Formatted task dicts
    """
    formatted = []
    for task in scheduled_tasks:
        eta = task.get("eta")  # eta absent for tasks without scheduled time
        eta_str = (
            datetime.fromisoformat(eta).strftime("%Y-%m-%d %H:%M:%S") if eta else "N/A"
        )

        formatted.append(
            {
                "task_id": task["id"],
                "task_name": task["name"].split(".")[-1],
                "eta": eta_str,
                # delivery_info may be absent for tasks without routing info
                "queue": task.get("delivery_info", {}).get("routing_key", "default"),
                "worker": task["worker"],
            }
        )
    return formatted


def format_revoked_tasks(revoked_list: list) -> list:
    """Format revoked tasks for AgGrid display with enrichment from result backend.

    Args:
        revoked_list: List of revoked tasks with id and worker fields

    Returns:
        list: List of task dictionaries formatted for table
    """
    tasks = []
    for task in revoked_list:
        task_id = task["id"]
        result_info = background_job_manager.get_task_result_info(task_id)

        tasks.append(
            {
                "task_id": task_id,
                "task_name": result_info["task_name"],
                "worker": task["worker"],
                "status": result_info["status"],
            }
        )
    return tasks


def format_worker_stats(overview):
    """Format worker statistics as cards.

    Args:
        overview: Task overview dict

    Returns:
        list: List of dbc.Card components
    """
    workers = overview["workers"]
    active_tasks = overview["active"]
    reserved_tasks = overview["reserved"]
    scheduled_tasks = overview["scheduled"]

    if not workers:
        return []

    cards = []
    for worker in workers:
        active_count = sum(1 for task in active_tasks if task["worker"] == worker)
        reserved_count = sum(1 for task in reserved_tasks if task["worker"] == worker)
        scheduled_count = sum(1 for task in scheduled_tasks if task["worker"] == worker)

        card = dbc.Card(
            dbc.CardBody(
                [
                    html.H5(worker, className="card-title"),
                    html.P(
                        [
                            f"Active: {active_count} | ",
                            f"Reserved: {reserved_count} | ",
                            f"Scheduled: {scheduled_count}",
                        ],
                        className="card-text",
                    ),
                ]
            ),
            className="mb-2",
            color="primary",
            outline=True,
        )
        cards.append(card)

    return cards


# ============================================================================
# Layout
# ============================================================================


def layout():
    """Create the worker management page layout."""
    header = create_header(
        "Worker Management",
        "Monitor and control Celery background workers",
        bg_color="bg-info",
        rounded=False,
    )

    refresh_controls = dbc.Row(
        [
            dbc.Col(
                [
                    dbc.Button(
                        [
                            html.I(className="bi bi-arrow-clockwise me-1"),
                            "Refresh",
                        ],
                        id=WORKER_REFRESH_BTN_WORKER_MANAGEMENT_ID,
                        color="primary",
                        className="me-2",
                    ),
                    dbc.Button(
                        [
                            html.I(className="bi bi-play me-1"),
                            "Submit Test Task",
                        ],
                        id=TEST_TASK_BUTTON_WORKER_MANAGEMENT_ID,
                        color="success",
                        className="me-2",
                    ),
                    html.Span(
                        "Last refresh: Never",
                        id=WORKER_LAST_REFRESH_DIV_WORKER_MANAGEMENT_ID,
                    ),
                ]
            )
        ],
        className="mb-4",
    )

    worker_stats = html.Div(
        id=WORKER_STATS_CARD_DIV_WORKER_MANAGEMENT_ID, className="mb-4"
    )

    active_section = create_task_section(
        title="Active Tasks",
        description="Currently running tasks on workers",
        table_id=ACTIVE_TASKS_TABLE_WORKER_MANAGEMENT_ID,
        columns=[
            {"id": "task_id", "name": "Task ID"},
            {"id": "task_name", "name": "Task Name"},
            {"id": "worker", "name": "Worker"},
            {"id": "start_time", "name": "Start Time"},
            {"id": "duration", "name": "Duration"},
            {"id": "job_id", "name": "Job ID"},
        ],
        button_id=WORKER_KILL_BTN_WORKER_MANAGEMENT_ID,
        button_label="Kill Selected Task",
        selectable=True,
        initially_disabled=True,
    )

    reserved_section = create_task_section(
        title="Reserved Tasks",
        description="Tasks claimed by workers but not yet started",
        table_id=RESERVED_TASKS_TABLE_WORKER_MANAGEMENT_ID,
        columns=[
            {"id": "task_id", "name": "Task ID"},
            {"id": "task_name", "name": "Task Name"},
            {"id": "queue", "name": "Queue"},
            {"id": "worker", "name": "Worker"},
        ],
        selectable=True,
    )

    scheduled_section = create_task_section(
        title="Scheduled Tasks",
        description="Tasks scheduled for future execution",
        table_id=SCHEDULED_TASKS_TABLE_WORKER_MANAGEMENT_ID,
        columns=[
            {"id": "task_id", "name": "Task ID"},
            {"id": "task_name", "name": "Task Name"},
            {"id": "eta", "name": "ETA"},
            {"id": "queue", "name": "Queue"},
        ],
        button_id=WORKER_CANCEL_BTN_WORKER_MANAGEMENT_ID,
        button_label="Cancel Selected Task",
        selectable=True,
    )

    revoked_section = create_task_section(
        title="Revoked Tasks",
        description="Cancelled or killed tasks",
        table_id=REVOKED_TASKS_TABLE_WORKER_MANAGEMENT_ID,
        columns=[
            {"id": "task_id", "name": "Task ID"},
            {"id": "task_name", "name": "Task Name"},
            {"id": "worker", "name": "Worker"},
            {"id": "status", "name": "Status"},
        ],
        selectable=False,
    )

    dummy = html.Div(
        id=WORKER_MANAGEMENT_DUMMY_COMPONENT_WORKER_MANAGEMENT_ID,
        className="d-none",
    )

    # Kill Confirmation Modal
    kill_modal = dbc.Modal(
        [
            dbc.ModalHeader("Confirm Task Termination"),
            dbc.ModalBody(
                [
                    html.P(
                        "WARNING: This will send SIGTERM to the worker process.",
                        className="text-danger fw-bold",
                    ),
                    html.P("The worker process will be killed immediately."),
                    html.Pre(
                        id=KILL_MODAL_TASK_INFO_DIV_WORKER_MANAGEMENT_ID,
                        className="bg-light p-2",
                    ),
                    html.P(
                        "Are you sure you want to KILL this task?",
                        className="fw-bold text-danger",
                    ),
                ]
            ),
            dbc.ModalFooter(
                [
                    dbc.Button(
                        [html.I(className="bi bi-x-circle me-1"), "Cancel"],
                        id=KILL_MODAL_CANCEL_BUTTON_WORKER_MANAGEMENT_ID,
                        color="secondary",
                    ),
                    dbc.Button(
                        [html.I(className="bi bi-x-octagon-fill me-1"), "Kill Task"],
                        id=KILL_MODAL_CONFIRM_BUTTON_WORKER_MANAGEMENT_ID,
                        color="danger",
                    ),
                ]
            ),
        ],
        id=KILL_MODAL_WORKER_MANAGEMENT_ID,
        is_open=False,
    )

    # Cancel Confirmation Modal
    cancel_modal = dbc.Modal(
        [
            dbc.ModalHeader("Confirm Task Cancellation"),
            dbc.ModalBody(
                [
                    html.P("This will prevent the task from executing."),
                    html.P(
                        "If the task is already running, it will continue until completion."
                    ),
                    html.Pre(
                        id=CANCEL_MODAL_TASK_INFO_DIV_WORKER_MANAGEMENT_ID,
                        className="bg-light p-2",
                    ),
                    html.P(
                        "Are you sure you want to CANCEL this task?",
                        className="fw-bold",
                    ),
                ]
            ),
            dbc.ModalFooter(
                [
                    dbc.Button(
                        [html.I(className="bi bi-x-circle me-1"), "Cancel"],
                        id=CANCEL_MODAL_CANCEL_BUTTON_WORKER_MANAGEMENT_ID,
                        color="secondary",
                    ),
                    dbc.Button(
                        [html.I(className="bi bi-x-circle me-1"), "Cancel Task"],
                        id=CANCEL_MODAL_CONFIRM_BUTTON_WORKER_MANAGEMENT_ID,
                        color="warning",
                    ),
                ]
            ),
        ],
        id=CANCEL_MODAL_WORKER_MANAGEMENT_ID,
        is_open=False,
    )

    page_content = dbc.Container(
        [
            refresh_controls,
            worker_stats,
            active_section,
            reserved_section,
            scheduled_section,
            revoked_section,
            dummy,
            kill_modal,
            cancel_modal,
        ],
        className="my-4",
        fluid=True,
    )

    return page_container_column_layout([header, page_content])


# ============================================================================
# Callbacks
# ============================================================================


# Clientside: open overlay instantly in the browser for the refresh button.
# Kill/cancel buttons open modals first; the confirm callbacks handle the overlay.
dash.clientside_callback(
    "function(n) { return true; }",
    Output(LOADING_OVERLAY_MODAL_SHARED_ID, "is_open", allow_duplicate=True),
    Input(WORKER_REFRESH_BTN_WORKER_MANAGEMENT_ID, "n_clicks"),
    prevent_initial_call=True,
)


@callback(
    output={
        "active_data": Output(ACTIVE_TASKS_TABLE_WORKER_MANAGEMENT_ID, "rowData"),
        "reserved_data": Output(RESERVED_TASKS_TABLE_WORKER_MANAGEMENT_ID, "rowData"),
        "scheduled_data": Output(SCHEDULED_TASKS_TABLE_WORKER_MANAGEMENT_ID, "rowData"),
        "revoked_data": Output(REVOKED_TASKS_TABLE_WORKER_MANAGEMENT_ID, "rowData"),
        "worker_cards": Output(WORKER_STATS_CARD_DIV_WORKER_MANAGEMENT_ID, "children"),
        "last_refresh": Output(
            WORKER_LAST_REFRESH_DIV_WORKER_MANAGEMENT_ID, "children"
        ),
        "loading": Output(
            LOADING_OVERLAY_MODAL_SHARED_ID, "is_open", allow_duplicate=True
        ),
        "active_selected": Output(
            ACTIVE_TASKS_TABLE_WORKER_MANAGEMENT_ID, "selectedRows"
        ),
        "reserved_selected": Output(
            RESERVED_TASKS_TABLE_WORKER_MANAGEMENT_ID, "selectedRows"
        ),
        "scheduled_selected": Output(
            SCHEDULED_TASKS_TABLE_WORKER_MANAGEMENT_ID, "selectedRows"
        ),
    },
    inputs={
        "refresh_clicks": Input(WORKER_REFRESH_BTN_WORKER_MANAGEMENT_ID, "n_clicks"),
        "dummy_data": Input(
            WORKER_MANAGEMENT_DUMMY_COMPONENT_WORKER_MANAGEMENT_ID, "children"
        ),
    },
    prevent_initial_call="initial_duplicate",
)
def refresh_worker_data(refresh_clicks, dummy_data):
    """Fetch and display current worker and task data."""
    log.info("Refreshing worker data")

    overview = background_job_manager.get_all_tasks_overview()
    log.debug(f"Retrieved task overview: {overview}")

    active_data = format_active_tasks(overview["active"])
    reserved_data = format_reserved_tasks(overview["reserved"])
    scheduled_data = format_scheduled_tasks(overview["scheduled"])
    revoked_data = format_revoked_tasks(overview["revoked"])

    worker_cards = format_worker_stats(overview)

    timestamp = datetime.now().strftime("%H:%M:%S")

    log.info(
        f"Worker data refreshed - {len(active_data)} active, "
        f"{len(reserved_data)} reserved, {len(scheduled_data)} scheduled, "
        f"{len(revoked_data)} revoked tasks"
    )

    return {
        "active_data": active_data,
        "reserved_data": reserved_data,
        "scheduled_data": scheduled_data,
        "revoked_data": revoked_data,
        "worker_cards": worker_cards,
        "last_refresh": f"Last refresh: {timestamp}",
        "loading": False,
        "active_selected": [],
        "reserved_selected": [],
        "scheduled_selected": [],
    }


@callback(
    Output(WORKER_KILL_BTN_WORKER_MANAGEMENT_ID, "disabled"),
    Input(ACTIVE_TASKS_TABLE_WORKER_MANAGEMENT_ID, "selectedRows"),
)
def enable_kill_button(selected_rows):
    """Enable kill button only when a task is selected."""
    return not selected_rows


@callback(
    Output(WORKER_CANCEL_BTN_WORKER_MANAGEMENT_ID, "disabled"),
    Input(RESERVED_TASKS_TABLE_WORKER_MANAGEMENT_ID, "selectedRows"),
    Input(SCHEDULED_TASKS_TABLE_WORKER_MANAGEMENT_ID, "selectedRows"),
)
def toggle_cancel_button(reserved_selected, scheduled_selected):
    """Enable cancel button when reserved or scheduled task selected."""
    return not (reserved_selected or scheduled_selected)


# --- Kill modal callbacks ---


@callback(
    Output(KILL_MODAL_WORKER_MANAGEMENT_ID, "is_open"),
    Output(KILL_MODAL_TASK_INFO_DIV_WORKER_MANAGEMENT_ID, "children"),
    Input(WORKER_KILL_BTN_WORKER_MANAGEMENT_ID, "n_clicks"),
    State(ACTIVE_TASKS_TABLE_WORKER_MANAGEMENT_ID, "selectedRows"),
    prevent_initial_call=True,
)
def open_kill_modal(n_clicks, selected_rows):
    """Open kill confirmation modal with task info."""
    if not selected_rows:
        return False, ""

    task = selected_rows[0]
    task_info = (
        f"Task: {task['task_name']}\n"
        f"ID: {task['task_id']}\n"
        f"Worker: {task['worker']}\n"
        f"Duration: {task['duration']}\n"
    )

    log.info(f"Opening kill modal for task {task['task_id']}")

    return True, task_info


@callback(
    Output(KILL_MODAL_WORKER_MANAGEMENT_ID, "is_open", allow_duplicate=True),
    Output(
        ACTIVE_TASKS_TABLE_WORKER_MANAGEMENT_ID,
        "selectedRows",
        allow_duplicate=True,
    ),
    Output(
        WORKER_MANAGEMENT_DUMMY_COMPONENT_WORKER_MANAGEMENT_ID,
        "children",
    ),
    Output(LOADING_OVERLAY_MODAL_SHARED_ID, "is_open", allow_duplicate=True),
    Input(KILL_MODAL_CONFIRM_BUTTON_WORKER_MANAGEMENT_ID, "n_clicks"),
    State(ACTIVE_TASKS_TABLE_WORKER_MANAGEMENT_ID, "selectedRows"),
    prevent_initial_call=True,
)
def confirm_kill_task(n_clicks, selected_rows):
    """Kill the selected task after modal confirmation."""
    if n_clicks is None:
        raise PreventUpdate
    if not selected_rows:
        log.warning("Kill task attempted with no selection")
        return False, [], no_update, False

    task = selected_rows[0]
    task_id = task["task_id"]

    background_job_manager.revoke_job(task_id, terminate=True)

    log.warning(f"Task {task_id} killed by user")

    return False, [], None, True


@callback(
    Output(KILL_MODAL_WORKER_MANAGEMENT_ID, "is_open", allow_duplicate=True),
    Input(KILL_MODAL_CANCEL_BUTTON_WORKER_MANAGEMENT_ID, "n_clicks"),
    prevent_initial_call=True,
)
def cancel_kill_modal(n_clicks):
    """Close kill modal without action."""
    return False


# --- Cancel modal callbacks ---


@callback(
    Output(CANCEL_MODAL_WORKER_MANAGEMENT_ID, "is_open"),
    Output(CANCEL_MODAL_TASK_INFO_DIV_WORKER_MANAGEMENT_ID, "children"),
    Input(WORKER_CANCEL_BTN_WORKER_MANAGEMENT_ID, "n_clicks"),
    State(RESERVED_TASKS_TABLE_WORKER_MANAGEMENT_ID, "selectedRows"),
    State(SCHEDULED_TASKS_TABLE_WORKER_MANAGEMENT_ID, "selectedRows"),
    prevent_initial_call=True,
)
def open_cancel_modal(n_clicks, reserved_selected, scheduled_selected):
    """Open cancel confirmation modal with task info."""
    task = None
    if reserved_selected:
        task = reserved_selected[0]
    elif scheduled_selected:
        task = scheduled_selected[0]

    if not task:
        return False, ""

    task_info = (
        f"Task: {task['task_name']}\nID: {task['task_id']}\nQueue: {task['queue']}\n"
    )

    log.info(f"Opening cancel modal for task {task['task_id']}")

    return True, task_info


@callback(
    Output(CANCEL_MODAL_WORKER_MANAGEMENT_ID, "is_open", allow_duplicate=True),
    Output(
        RESERVED_TASKS_TABLE_WORKER_MANAGEMENT_ID,
        "selectedRows",
        allow_duplicate=True,
    ),
    Output(
        SCHEDULED_TASKS_TABLE_WORKER_MANAGEMENT_ID,
        "selectedRows",
        allow_duplicate=True,
    ),
    Output(
        WORKER_MANAGEMENT_DUMMY_COMPONENT_WORKER_MANAGEMENT_ID,
        "children",
        allow_duplicate=True,
    ),
    Output(LOADING_OVERLAY_MODAL_SHARED_ID, "is_open", allow_duplicate=True),
    Input(CANCEL_MODAL_CONFIRM_BUTTON_WORKER_MANAGEMENT_ID, "n_clicks"),
    State(RESERVED_TASKS_TABLE_WORKER_MANAGEMENT_ID, "selectedRows"),
    State(SCHEDULED_TASKS_TABLE_WORKER_MANAGEMENT_ID, "selectedRows"),
    prevent_initial_call=True,
)
def confirm_cancel_task(n_clicks, reserved_selected, scheduled_selected):
    """Cancel the selected task after modal confirmation."""
    if n_clicks is None:
        raise PreventUpdate

    task = None
    if reserved_selected:
        task = reserved_selected[0]
    elif scheduled_selected:
        task = scheduled_selected[0]

    if not task:
        log.warning("Cancel task attempted with no selection")
        return False, [], [], no_update, False

    task_id = task["task_id"]

    background_job_manager.revoke_job(task_id, terminate=False)

    log.warning(f"Task {task_id} ({task['task_name']}) cancelled by user")

    return False, [], [], None, True


@callback(
    Output(CANCEL_MODAL_WORKER_MANAGEMENT_ID, "is_open", allow_duplicate=True),
    Input(CANCEL_MODAL_CANCEL_BUTTON_WORKER_MANAGEMENT_ID, "n_clicks"),
    prevent_initial_call=True,
)
def cancel_cancel_modal(n_clicks):
    """Close cancel modal without action."""
    return False


@callback(
    Output(
        WORKER_MANAGEMENT_DUMMY_COMPONENT_WORKER_MANAGEMENT_ID,
        "children",
        allow_duplicate=True,
    ),
    Output(LOADING_OVERLAY_MODAL_SHARED_ID, "is_open", allow_duplicate=True),
    Input(TEST_TASK_BUTTON_WORKER_MANAGEMENT_ID, "n_clicks"),
    prevent_initial_call=True,
)
def submit_test_task(n_clicks):
    """Submit a test sleep task when button is clicked."""
    log.info("Test task button clicked")
    if n_clicks is None:
        raise PreventUpdate

    task_id, failed = background_job_manager.submit_test_task()

    if failed:
        log.error("Failed to submit test task")
    else:
        log.info(f"Test task submitted successfully with task_id={task_id}")

    return None, True


# Registered with an explicit "pages.*" key + layout so an app can import this
# framework page across the package boundary (not via local pages_folder discovery).
register_page(
    "pages.worker_management",
    path="/worker-management",
    name="Worker Management",
    title="Cosmo Ecosystem - Worker Management",
    description="Monitor and control Celery background workers and tasks.",
    layout=layout,
)
