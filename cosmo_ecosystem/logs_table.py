"""Shared logs table component for displaying logs across pages."""

import dash_bootstrap_components as dbc
from dash import html


def level_badge(level: str) -> dbc.Badge:
    """Format log level with color-coded badge."""
    color_map = {
        "DEBUG": "secondary",
        "INFO": "info",
        "WARNING": "warning",
        "ERROR": "danger",
        "CRITICAL": "dark",
    }
    # dispatch lookup: level comes from log records, fallback for unexpected levels
    return dbc.Badge(level, color=color_map.get(level, "primary"), className="me-1")


def format_logs_list(logs: list, show_pid: bool = True) -> html.Ul:
    """Format a list of log records as an html.Ul component.

    Args:
        logs: List of log dictionaries with keys: level, timestamp, module, message,
              and optionally pid

    Returns:
        html.Ul component with formatted log entries
    """
    items = []
    for log in logs:
        content = [level_badge(log["level"])]

        content.append(f" at {log['timestamp']} ")
        content.append(f"in {log['module']}")

        if show_pid and "pid" in log:
            content.append(f" [PID {log['pid']}]")

        content.append(f":\n{log['message']}")

        items.append(
            html.Li(
                content,
                # no Bootstrap class for white-space: pre-wrap
                style={"white-space": "pre-wrap"},
            )
        )

    return html.Ul(items)


def create_logs_container(
    container_id: str,
    default_content: str = "Logs will appear here...",
    max_height: str = "70vh",
) -> html.Div:
    """Create a styled container for logs display.

    Args:
        container_id: The ID for the container element
        default_content: Initial content to display
        max_height: Maximum height of the container (CSS value)

    Returns:
        html.Div styled as a logs container
    """
    return html.Div(
        id=container_id,  # nocheck
        children=default_content,
        className="border p-3 bg-light rounded",
        # no Bootstrap class for dynamic maxHeight + overflow scroll
        style={"maxHeight": max_height, "overflowY": "auto"},
    )
