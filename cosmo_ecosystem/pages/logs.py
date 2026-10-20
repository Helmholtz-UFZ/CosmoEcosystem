"""View and filter application logs for debugging and monitoring.

This page provides access to the application's logging system, allowing you to track
system activity, debug issues, and monitor operations. You can:

- Filter logs by date and time range
- Select specific log levels (Debug, Info, Warning, Error, Critical)
- Filter by process ID to track specific worker or server processes
- Exclude specific modules from the output
- Enable live mode for automatic 10-second polling (on by default)
- View logs in a formatted, readable table
- Refresh logs on demand to see latest entries

Logs are stored in the database and include timestamps, log levels, logger names,
and messages. This is the primary tool for understanding system behavior, diagnosing
problems, and monitoring background job execution.

NOTE: This docstring is displayed on the documentation webpage.
"""

import datetime

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, ctx, dcc, html, no_update

from cosmo_ecosystem.constants import (
    AUTO_POLL_INTERVAL_LOGS_ID,
    DATE_RANGE_DATEPICKER_LOGS_ID,
    END_HOUR_INPUT_LOGS_ID,
    END_MINUTE_INPUT_LOGS_ID,
    LIVE_MODE_CHECKLIST_LOGS_ID,
    LOG_LEVELS_DROPDOWN_LOGS_ID,
    LOG_OUTPUT_DIV_LOGS_ID,
    MODULE_EXCLUDE_DROPDOWN_LOGS_ID,
    PID_INPUT_LOGS_ID,
    PID_RADIO_CHECKLIST_LOGS_ID,
    REFRESH_BUTTON_LOGS_ID,
    START_HOUR_INPUT_LOGS_ID,
    START_MINUTE_INPUT_LOGS_ID,
    TIME_ERROR_DIV_LOGS_ID,
    TIME_INPUT_GROUP_LOGS_ID,
)
from cosmo_ecosystem.layouts import create_header, page_container_column_layout
from cosmo_ecosystem.logs_table import format_logs_list
from cosmo_ecosystem.db_manager import DbManager

DEFAULT_EXCLUDED_MODULES = ["beat", "logs", "layout", "db_manager"]


def layout():
    """Dynamic layout that calculates current time on each page visit."""
    now = datetime.datetime.now()
    start_hour = now.hour - 1 if now.hour > 0 else 23
    start_minute = now.minute
    end_hour = now.hour
    end_minute = now.minute

    # Populate module exclusion options from DB
    all_modules = DbManager.query_distinct_modules()
    module_options = [{"label": m, "value": m} for m in all_modules]
    default_excluded = [m for m in DEFAULT_EXCLUDED_MODULES if m in all_modules]

    header = create_header(
        "View logs", "Show logs of the webserver", bg_color="bg-info"
    )

    # Polling interval (starts enabled — live mode on by default)
    interval = dcc.Interval(
        id=AUTO_POLL_INTERVAL_LOGS_ID,
        interval=10_000,
        disabled=False,
    )

    # Row 1: Date + Time range + Live toggle
    date_selector = [
        html.Label("Select Date"),
        html.Br(),
        dcc.DatePickerSingle(
            id=DATE_RANGE_DATEPICKER_LOGS_ID,
            date=now.date(),
            disabled=True,
        ),
    ]

    time_selector = [
        html.Label("Time Range"),
        html.Div(
            children=[
                dbc.InputGroup(
                    [
                        dbc.InputGroupText("From"),
                        dbc.Input(
                            id=START_HOUR_INPUT_LOGS_ID,
                            type="number",
                            value=start_hour,
                            min=0,
                            max=23,
                        ),
                        dbc.InputGroupText(":"),
                        dbc.Input(
                            id=START_MINUTE_INPUT_LOGS_ID,
                            type="number",
                            value=start_minute,
                            min=0,
                            max=59,
                        ),
                        dbc.InputGroupText("To"),
                        dbc.Input(
                            id=END_HOUR_INPUT_LOGS_ID,
                            type="number",
                            value=end_hour,
                            min=0,
                            max=23,
                            disabled=True,
                        ),
                        dbc.InputGroupText(":"),
                        dbc.Input(
                            id=END_MINUTE_INPUT_LOGS_ID,
                            type="number",
                            value=end_minute,
                            min=0,
                            max=59,
                            disabled=True,
                        ),
                    ],
                    id=TIME_INPUT_GROUP_LOGS_ID,
                ),
                html.Small(id=TIME_ERROR_DIV_LOGS_ID, className="text-danger"),
            ],
        ),
    ]

    live_toggle = [
        html.Label("Live"),
        dbc.Checklist(
            id=LIVE_MODE_CHECKLIST_LOGS_ID,
            options=[{"label": "Auto-refresh", "value": "on"}],
            value=["on"],
            switch=True,
        ),
    ]

    # Row 2: Log levels + PID + Module exclusion
    log_levels = [
        html.Label("Log Levels"),
        dcc.Dropdown(
            id=LOG_LEVELS_DROPDOWN_LOGS_ID,
            options=[
                {"label": "Debug", "value": "DEBUG"},
                {"label": "Info", "value": "INFO"},
                {"label": "Warning", "value": "WARNING"},
                {"label": "Error", "value": "ERROR"},
                {"label": "Critical", "value": "CRITICAL"},
            ],
            value=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
            multi=True,
        ),
    ]

    pid_selector = [
        html.Label("PID"),
        dbc.InputGroup(
            [
                dbc.InputGroupText(
                    dbc.Checklist(
                        id=PID_RADIO_CHECKLIST_LOGS_ID,
                        options=[{"label": "Filter by PID", "value": "on"}],
                        value=[],
                        switch=True,
                    ),
                ),
                dbc.Input(
                    id=PID_INPUT_LOGS_ID,
                    type="number",
                    placeholder="Process ID",
                    disabled=True,
                ),
            ],
        ),
    ]

    module_exclusion = [
        html.Label("Exclude Modules"),
        dcc.Dropdown(
            id=MODULE_EXCLUDE_DROPDOWN_LOGS_ID,
            options=module_options,
            value=default_excluded,
            multi=True,
            placeholder="Select modules to exclude...",
        ),
    ]

    # Row 3: Refresh button (right-aligned)
    refresh_row = dbc.Row(
        dbc.Col(
            dbc.Button(
                "Refresh",
                id=REFRESH_BUTTON_LOGS_ID,
                color="primary",
                disabled=True,
            ),
            className="d-flex justify-content-end",
        ),
        className="mb-4",
    )

    page_layout = [
        header,
        interval,
        dbc.Container(
            [
                dbc.Row(
                    [
                        dbc.Col(date_selector, width=4),
                        dbc.Col(time_selector, width=6),
                        dbc.Col(live_toggle, width=2),
                    ],
                    className="mb-4",
                ),
                dbc.Row(
                    [
                        dbc.Col(log_levels, width=4),
                        dbc.Col(pid_selector, width=4),
                        dbc.Col(module_exclusion, width=4),
                    ],
                    className="mb-4",
                ),
                refresh_row,
                html.Div(
                    id=LOG_OUTPUT_DIV_LOGS_ID,
                    children="Live mode active — waiting for first refresh...",
                    className="border p-3 bg-light rounded",
                    # no Bootstrap class for dynamic maxHeight + overflow scroll
                    style={"maxHeight": "70vh", "overflowY": "auto"},
                ),
            ],
            className="my-4",
        ),
    ]

    return page_container_column_layout(page_layout)


# ============================================================================
# Callbacks
# ============================================================================


def _query_and_format(
    date,
    start_hour,
    start_minute,
    end_hour,
    end_minute,
    levels,
    pid_checklist,
    pid,
    excluded_modules,
):
    """Validate inputs, query DB, return (content, disabled_pid, error, class)."""
    disabled_pid = "on" not in pid_checklist
    if disabled_pid:
        pid = None

    bad_values_log = "Select a valid time range."
    bad_input_group_class = "border border-danger rounded"

    if None in (start_hour, start_minute, end_hour, end_minute):
        return (
            bad_values_log,
            disabled_pid,
            "All time fields must be filled.",
            bad_input_group_class,
        )

    if (start_hour, start_minute) >= (end_hour, end_minute):
        return (
            bad_values_log,
            disabled_pid,
            "Start time must be before end time.",
            bad_input_group_class,
        )

    logs = DbManager.query_logs(
        date,
        start_hour,
        start_minute,
        end_hour,
        end_minute,
        levels,
        pid,
        excluded_modules,
    )

    if not logs:
        return "No logs found for the selected criteria.", disabled_pid, "", ""

    return format_logs_list(logs, show_pid=True), disabled_pid, "", ""


def _no_update_result():
    """Return a dict with no_update for all control outputs."""
    return {
        "interval_disabled": no_update,
        "end_hour_value": no_update,
        "end_minute_value": no_update,
        "end_hour_disabled": no_update,
        "end_minute_disabled": no_update,
        "date_value": no_update,
        "date_disabled": no_update,
        "start_hour_value": no_update,
        "start_minute_value": no_update,
        "refresh_disabled": no_update,
    }


@callback(
    output={
        "log_content": Output(LOG_OUTPUT_DIV_LOGS_ID, "children"),
        "pid_disabled": Output(PID_INPUT_LOGS_ID, "disabled"),
        "time_error": Output(TIME_ERROR_DIV_LOGS_ID, "children"),
        "time_group_class": Output(TIME_INPUT_GROUP_LOGS_ID, "className"),
        "interval_disabled": Output(AUTO_POLL_INTERVAL_LOGS_ID, "disabled"),
        "end_hour_value": Output(END_HOUR_INPUT_LOGS_ID, "value"),
        "end_minute_value": Output(END_MINUTE_INPUT_LOGS_ID, "value"),
        "end_hour_disabled": Output(END_HOUR_INPUT_LOGS_ID, "disabled"),
        "end_minute_disabled": Output(END_MINUTE_INPUT_LOGS_ID, "disabled"),
        "date_value": Output(DATE_RANGE_DATEPICKER_LOGS_ID, "date"),
        "date_disabled": Output(DATE_RANGE_DATEPICKER_LOGS_ID, "disabled"),
        "start_hour_value": Output(START_HOUR_INPUT_LOGS_ID, "value"),
        "start_minute_value": Output(START_MINUTE_INPUT_LOGS_ID, "value"),
        "refresh_disabled": Output(REFRESH_BUTTON_LOGS_ID, "disabled"),
    },
    inputs={
        "n_intervals": Input(AUTO_POLL_INTERVAL_LOGS_ID, "n_intervals"),
        "n_clicks": Input(REFRESH_BUTTON_LOGS_ID, "n_clicks"),
        "live_checklist": Input(LIVE_MODE_CHECKLIST_LOGS_ID, "value"),
    },
    state={
        "date": State(DATE_RANGE_DATEPICKER_LOGS_ID, "date"),
        "start_hour": State(START_HOUR_INPUT_LOGS_ID, "value"),
        "start_minute": State(START_MINUTE_INPUT_LOGS_ID, "value"),
        "end_hour": State(END_HOUR_INPUT_LOGS_ID, "value"),
        "end_minute": State(END_MINUTE_INPUT_LOGS_ID, "value"),
        "levels": State(LOG_LEVELS_DROPDOWN_LOGS_ID, "value"),
        "pid_checklist": State(PID_RADIO_CHECKLIST_LOGS_ID, "value"),
        "pid": State(PID_INPUT_LOGS_ID, "value"),
        "excluded_modules": State(MODULE_EXCLUDE_DROPDOWN_LOGS_ID, "value"),
    },
    prevent_initial_call=True,
)
def log_manager(
    n_intervals,
    n_clicks,
    live_checklist,
    date,
    start_hour,
    start_minute,
    end_hour,
    end_minute,
    levels,
    pid_checklist,
    pid,
    excluded_modules,
):
    """Manage and display logs based on user input."""
    trigger = ctx.triggered_id

    if trigger == LIVE_MODE_CHECKLIST_LOGS_ID:
        live = "on" in live_checklist

        if live:
            now = datetime.datetime.now()
            today = str(now.date())
            live_start_hour = (
                now.hour if now.minute >= 5 else (now.hour - 1 if now.hour > 0 else 23)
            )
            live_start_minute = (now.minute - 5) % 60

            content, disabled_pid, error, cls = _query_and_format(
                today,
                live_start_hour,
                live_start_minute,
                now.hour,
                now.minute,
                levels,
                pid_checklist,
                pid,
                excluded_modules,
            )
            return {
                "log_content": content,
                "pid_disabled": disabled_pid,
                "time_error": error,
                "time_group_class": cls,
                "interval_disabled": False,
                "end_hour_value": now.hour,
                "end_minute_value": now.minute,
                "end_hour_disabled": True,
                "end_minute_disabled": True,
                "date_value": today,
                "date_disabled": True,
                "start_hour_value": live_start_hour,
                "start_minute_value": live_start_minute,
                "refresh_disabled": True,
            }

        # Live OFF
        content, disabled_pid, error, cls = _query_and_format(
            date,
            start_hour,
            start_minute,
            end_hour,
            end_minute,
            levels,
            pid_checklist,
            pid,
            excluded_modules,
        )
        result = _no_update_result()
        result.update(
            {
                "log_content": content,
                "pid_disabled": disabled_pid,
                "time_error": error,
                "time_group_class": cls,
                "interval_disabled": True,
                "end_hour_disabled": False,
                "end_minute_disabled": False,
                "date_disabled": False,
                "refresh_disabled": False,
            }
        )
        return result

    if trigger == AUTO_POLL_INTERVAL_LOGS_ID:
        now = datetime.datetime.now()

        content, disabled_pid, error, cls = _query_and_format(
            date,
            start_hour,
            start_minute,
            now.hour,
            now.minute,
            levels,
            pid_checklist,
            pid,
            excluded_modules,
        )
        result = _no_update_result()
        result.update(
            {
                "log_content": content,
                "pid_disabled": disabled_pid,
                "time_error": error,
                "time_group_class": cls,
                "end_hour_value": now.hour,
                "end_minute_value": now.minute,
            }
        )
        return result

    if trigger == REFRESH_BUTTON_LOGS_ID:
        content, disabled_pid, error, cls = _query_and_format(
            date,
            start_hour,
            start_minute,
            end_hour,
            end_minute,
            levels,
            pid_checklist,
            pid,
            excluded_modules,
        )
        result = _no_update_result()
        result.update(
            {
                "log_content": content,
                "pid_disabled": disabled_pid,
                "time_error": error,
                "time_group_class": cls,
            }
        )
        return result


# Registered with an explicit "pages.*" key + layout so an app can import this
# framework page across the package boundary (not via local pages_folder discovery).
dash.register_page(
    "pages.logs",
    path_template="/logs",
    layout=layout,
)
