"""Tests for the framework job management page and its ``job_link`` seam.

The page is imported by both apps unchanged, so the one thing that differs between
them, where a job row links to, is a seam the app must set before the import.
Unset, the page would render a table of dead links; it refuses to import instead.
"""

import importlib
import sys
from datetime import datetime

import dash
import pytest
from dash._callback import GLOBAL_CALLBACK_LIST

from cosmo_ecosystem import pages
from cosmo_ecosystem.constants import (
    CLEAN_BUTTON_JOB_MANAGEMENT_ID,
    DELETE_BUTTON_JOB_MANAGEMENT_ID,
    LOADING_OVERLAY_MODAL_SHARED_ID,
    REFRESH_BUTTON_JOB_MANAGEMENT_ID,
)
from cosmo_ecosystem.error_handling import JobLinkNotConfigured

PAGE_MODULE = "cosmo_ecosystem.pages.job_management"
OVERLAY_OUTPUT = f"{LOADING_OVERLAY_MODAL_SHARED_ID}.is_open"


def _link_by_status(job_id, row):
    """A link that needs more than the id, as COSMONAUT's does."""
    return f"/{row['stage']}/{job_id}"


@pytest.fixture(scope="module")
def job_management():
    """Import the page once, the way an app does: seam set, app created first.

    ``register_page`` needs a Dash app to exist. The import also registers the
    page's callbacks in Dash's process-global list, so it happens once per module.
    """
    dash.Dash(__name__, use_pages=True, pages_folder="")
    pages.job_link = _link_by_status
    module = importlib.import_module(PAGE_MODULE)
    yield module
    pages.job_link = None


def test_import_without_job_link_raises_naming_the_seam(job_management):
    """No default link: an app that forgets the seam fails at startup."""
    sys.modules.pop(PAGE_MODULE)
    pages.job_link = None
    try:
        with pytest.raises(
            JobLinkNotConfigured, match=r"cosmo_ecosystem\.pages\.job_link"
        ):
            importlib.import_module(PAGE_MODULE)
    finally:
        sys.modules[PAGE_MODULE] = job_management
        pages.job_link = _link_by_status


def test_rows_link_where_job_link_says_with_the_full_row(job_management):
    """The link function sees every column, including one the framework never reads."""
    jobs = {
        "abc123": {
            "status": "PENDING",
            "start_date": datetime(2026, 10, 29, 14, 5, 9),
            "submitted": False,
            "stage": "route_computation",
        }
    }

    rows = job_management.build_rows(jobs)

    assert rows == [
        {
            "job_id": "[abc123](/route_computation/abc123)",
            "status": "PENDING",
            "start_date": "2026-10-29 14:05:09",
            "submitted": "No",
        }
    ]


def _overlay_callbacks_on_page_buttons():
    """Callbacks writing the shared overlay that listen to this page's buttons."""
    buttons = {
        DELETE_BUTTON_JOB_MANAGEMENT_ID,
        CLEAN_BUTTON_JOB_MANAGEMENT_ID,
        REFRESH_BUTTON_JOB_MANAGEMENT_ID,
    }
    return [
        cb
        for cb in GLOBAL_CALLBACK_LIST
        if OVERLAY_OUTPUT in cb["output"] and buttons <= {i["id"] for i in cb["inputs"]}
    ]


def test_overlay_opener_is_clientside(job_management):
    """A server-side opener can land after the closer and leave the overlay stuck.

    callbacks.md: the opener is clientside and listens to the buttons only, so its
    allow_duplicate id differs from the processing callback's.
    """
    callbacks = _overlay_callbacks_on_page_buttons()
    clientside = [cb for cb in callbacks if cb["clientside_function"] is not None]
    server_side = [cb for cb in callbacks if cb["clientside_function"] is None]

    assert len(clientside) == 1
    assert {i["id"] for i in clientside[0]["inputs"]} == {
        DELETE_BUTTON_JOB_MANAGEMENT_ID,
        CLEAN_BUTTON_JOB_MANAGEMENT_ID,
        REFRESH_BUTTON_JOB_MANAGEMENT_ID,
    }
    # The only server-side writer left is the processing callback, which closes it.
    assert len(server_side) == 1
    assert len(server_side[0]["inputs"]) == 4
