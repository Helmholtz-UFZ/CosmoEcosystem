"""View profiling results for a completed job.

Displays summary statistics, missing values chart, correlation heatmap,
and per-column distribution charts. Reached via /results/<job_id>.
"""

import json
import logging
import os

import dash
import dash_ag_grid as dag
import dash_bootstrap_components as dbc
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, callback, dcc, html

from cosmo_ecosystem.error_handling import InvalidJobID, JobNotFound
from cosmo_ecosystem.files_route import create_download_button
from cosmo_ecosystem.job import Job
from cosmo_ecosystem.layouts import (
    create_job_header,
    job_not_found_layout,
    landing_page_layout_column,
)

from csv_profiler.constants import (
    BACK_BUTTON_RESULTS_ID,
    HEADER_DIV_RESULTS_ID,
    JOB_STORE_RESULTS_ID,
    MAIN_CONTENT_DIV_RESULTS_ID,
    SUMMARY_TABLE_RESULTS_ID,
)

log = logging.getLogger(__name__)

dash.register_page(
    __name__,
    path_template="/results/<job_id>",
)


def layout(job_id):
    """Create the results page layout — loading state until callback fires."""
    return landing_page_layout_column(
        header_title="Results",
        header_id=HEADER_DIV_RESULTS_ID,
        job_id_store=JOB_STORE_RESULTS_ID,
        job_id=job_id,
        main_content_id=MAIN_CONTENT_DIV_RESULTS_ID,
    )


@callback(
    Output(HEADER_DIV_RESULTS_ID, "children"),
    Output(MAIN_CONTENT_DIV_RESULTS_ID, "children"),
    Input(JOB_STORE_RESULTS_ID, "data"),
    prevent_initial_call=False,
)
def load_results(job_id):
    """Load and render profiling results for the given job."""
    if not job_id:
        return dash.no_update, dash.no_update

    try:
        job = Job(job_id=job_id)
    except (InvalidJobID, JobNotFound) as e:
        log.info(f"Job not accessible {job_id}: {e}")
        return job_not_found_layout(job_id)

    result_path = os.path.join(job.working_dir, "result.json")
    if not os.path.exists(result_path):
        message = (
            f"Job status: {job.status}. Results not available yet."
            if job.status != "COMPLETED"
            else "Result file not found."
        )
        return (
            create_job_header("Results", job),
            html.Div(message, className="text-center text-warning m-3"),
        )

    with open(result_path, "r", encoding="UTF-8") as f:
        result = json.load(f)

    sections = []

    # Navigation buttons
    sections.append(
        dbc.Row(
            dbc.Col(
                [
                    dbc.Button(
                        [
                            html.I(className="bi bi-arrow-left me-1"),
                            "Back to Submission",
                        ],
                        id=BACK_BUTTON_RESULTS_ID,
                        color="secondary",
                        className="me-2",
                        href=f"/job-submission/{job_id}",
                    ),
                    create_download_button(job_id, class_name=""),
                ],
                className="d-flex justify-content-center gap-2",
            ),
            className="m-3",
        )
    )

    # 1. Overview
    sections.append(
        dbc.Row(
            dbc.Col(
                dbc.Card(
                    dbc.CardBody(
                        [
                            html.Span(
                                f"{result['row_count']} rows",
                                className="badge bg-primary me-2 fs-6",
                            ),
                            html.Span(
                                f"{result['column_count']} columns",
                                className="badge bg-secondary me-2 fs-6",
                            ),
                            html.Span(
                                f"Status: {job.status}",
                                className=f"badge {job.status_color()} fs-6",
                            ),
                        ],
                        className="text-center",
                    ),
                ),
            ),
            className="m-3",
        )
    )

    # 2. Summary statistics table
    summary_rows = _build_summary_rows(result["summary"])
    sections.append(
        html.Div(
            [
                html.H4("Summary Statistics", className="text-center mt-3"),
                dag.AgGrid(
                    id=SUMMARY_TABLE_RESULTS_ID,
                    columnDefs=[
                        {"field": "column", "headerName": "Column"},
                        {"field": "dtype", "headerName": "Type"},
                        {"field": "count", "headerName": "Count"},
                        {"field": "mean", "headerName": "Mean"},
                        {"field": "median", "headerName": "Median"},
                        {"field": "std", "headerName": "Std"},
                        {"field": "min", "headerName": "Min"},
                        {"field": "max", "headerName": "Max"},
                        {"field": "unique", "headerName": "Unique"},
                        {"field": "most_common", "headerName": "Most Common"},
                    ],
                    rowData=summary_rows,
                    defaultColDef={"cellStyle": {"textAlign": "center"}},
                    columnSize="responsiveSizeToFit",
                    style={"height": f"{min(60 + len(summary_rows) * 42, 500)}px"},
                ),
            ],
            className="m-3",
        )
    )

    # 3. Missing values bar chart
    missing = result["missing_values"]
    any_missing = any(v["count"] > 0 for v in missing.values())
    if any_missing:
        cols_with_missing = {k: v for k, v in missing.items() if v["count"] > 0}
        fig_missing = px.bar(
            x=[v["percent"] for v in cols_with_missing.values()],
            y=list(cols_with_missing.keys()),
            orientation="h",
            labels={"x": "Missing %", "y": "Column"},
            title="Missing Values",
        )
        fig_missing.update_layout(showlegend=False, margin=dict(l=20, r=20, t=40, b=20))
        sections.append(
            html.Div(
                dcc.Graph(figure=fig_missing),
                className="m-3",
            )
        )

    # 4. Correlation heatmap
    corr = result["correlation_matrix"]
    if corr and "columns" in corr and len(corr["columns"]) >= 2:
        fig_corr = go.Figure(
            data=go.Heatmap(
                z=corr["values"],
                x=corr["columns"],
                y=corr["columns"],
                colorscale="RdBu_r",
                zmid=0,
                text=[
                    [f"{v:.2f}" if v is not None else "" for v in row]
                    for row in corr["values"]
                ],
                texttemplate="%{text}",
            )
        )
        fig_corr.update_layout(
            title="Correlation Matrix",
            margin=dict(l=20, r=20, t=40, b=20),
        )
        sections.append(
            html.Div(
                dcc.Graph(figure=fig_corr),
                className="m-3",
            )
        )

    # 5. Per-column detail cards
    detail_cards = _build_column_detail_cards(result)
    if detail_cards:
        sections.append(
            html.Div(
                [
                    html.H4("Column Details", className="text-center mt-3"),
                    *detail_cards,
                ],
                className="m-3",
            )
        )

    return create_job_header("Profiling Results", job), html.Div(sections)


def _build_summary_rows(summary):
    """Build row data for the summary AG Grid table."""
    rows = []
    for col_name, stats in summary.items():
        row = {"column": col_name, "dtype": stats["dtype"]}
        if stats["dtype"] == "numeric":
            row.update(
                {
                    "count": stats["count"],
                    "mean": _fmt(stats["mean"]),
                    "median": _fmt(stats["median"]),
                    "std": _fmt(stats["std"]),
                    "min": _fmt(stats["min"]),
                    "max": _fmt(stats["max"]),
                    "unique": "",
                    "most_common": "",
                }
            )
        else:
            row.update(
                {
                    "count": stats["count"],
                    "mean": "",
                    "median": "",
                    "std": "",
                    "min": "",
                    "max": "",
                    "unique": stats["unique"],
                    "most_common": stats["most_common"],
                }
            )
        rows.append(row)
    return rows


def _fmt(val):
    """Format a numeric value for display."""
    if val is None:
        return ""
    return f"{val:.4g}"


def _build_column_detail_cards(result):
    """Build expandable detail cards with histograms/bar charts per column."""
    cards = []

    # Numeric columns: histograms
    for col_name, hist_data in result["histograms"].items():
        bin_edges = hist_data["bin_edges"]
        # Use bin centers for x-axis
        centers = [
            (bin_edges[i] + bin_edges[i + 1]) / 2 for i in range(len(bin_edges) - 1)
        ]
        fig = px.bar(
            x=centers,
            y=hist_data["values"],
            labels={"x": col_name, "y": "Count"},
            title=f"Distribution: {col_name}",
        )
        fig.update_layout(
            margin=dict(l=20, r=20, t=40, b=20),
            showlegend=False,
            bargap=0.05,
        )
        cards.append(
            dbc.Accordion(
                dbc.AccordionItem(
                    dcc.Graph(figure=fig),
                    title=f"{col_name} (numeric)",
                ),
                start_collapsed=True,
                className="mb-2",
            )
        )

    # Categorical columns: bar charts of top values
    for col_name, vc_data in result["value_counts"].items():
        fig = px.bar(
            x=list(vc_data.values()),
            y=list(vc_data.keys()),
            orientation="h",
            labels={"x": "Count", "y": col_name},
            title=f"Top Values: {col_name}",
        )
        fig.update_layout(
            margin=dict(l=20, r=20, t=40, b=20),
            showlegend=False,
            yaxis=dict(autorange="reversed"),
        )
        cards.append(
            dbc.Accordion(
                dbc.AccordionItem(
                    dcc.Graph(figure=fig),
                    title=f"{col_name} (categorical)",
                ),
                start_collapsed=True,
                className="mb-2",
            )
        )

    return cards
