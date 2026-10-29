"""Job reset for the CSV profiler: a confirmation modal in front of ``Job.reset``.

A page triggers it by writing ``{"job_id": …, "action": …}`` into
RESET_JOB_STORE_SHARED_ID. Two actions exist:

- ``"resubmit"``: reset, submit, go to ``/job-submission/<job_id>``;
- ``"change_input"``: reset, go to ``/input/<job_id>``.

Anything else raises ``ValueError``. Until v0.13.0 this lived in the framework
(``app_layout(with_reset=True)``) and fell through to a plain reset for any
action it did not know. It moved here because it builds the concrete ``Job`` and
calls ``Job.reset``, which ``BaseJob`` does not have; neither COSMOPOLITAN nor
COSMONAUT used it.
"""

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, callback_context, dcc

from cosmo_ecosystem.constants import (
    LOADING_OVERLAY_MODAL_SHARED_ID,
    URL_LOCATION_SHARED_ID,
)
from cosmo_ecosystem.job import Job

from csv_profiler.constants import (
    RESET_BODY_DIV_SHARED_ID,
    RESET_CANCEL_BUTTON_SHARED_ID,
    RESET_CONFIRM_BUTTON_SHARED_ID,
    RESET_CONFIRM_MODAL_SHARED_ID,
    RESET_JOB_STORE_SHARED_ID,
)

RESET_MESSAGES = {
    "resubmit": (
        "This will reset the job to PENDING, delete all results, and resubmit."
    ),
    "change_input": "This will reset the job to PENDING and delete all results.",
}


def _check_action(action):
    """Raise ``ValueError`` for an action the reset does not handle."""
    if action not in RESET_MESSAGES:
        raise ValueError(
            f"Unknown job reset action {action!r}; "
            f"expected one of {sorted(RESET_MESSAGES)}"
        )


def reset_message(action):
    """Return the confirmation text the modal shows for ``action``."""
    _check_action(action)
    return RESET_MESSAGES[action]


def reset_job(job_id, action):
    """Reset the job, resubmit it for ``"resubmit"``, and return the path to go to."""
    _check_action(action)
    job = Job(job_id=job_id)
    job.reset()
    if action == "resubmit":
        job.submit()
        return f"/job-submission/{job.job_id}"
    return f"/input/{job.job_id}"


def job_reset_components():
    """Return the reset modal and its store, and register their callbacks.

    The app appends these to its shell layout. Mounting and wiring happen in one
    call for the same reason ``app_layout`` registers the navbar toggle: the
    callbacks are wanted exactly where the components are on the page.
    """
    register_reset_callbacks()
    modal = dbc.Modal(
        [
            dbc.ModalHeader("Confirm Reset"),
            dbc.ModalBody(id=RESET_BODY_DIV_SHARED_ID),
            dbc.ModalFooter(
                [
                    dbc.Button(
                        "Cancel",
                        id=RESET_CANCEL_BUTTON_SHARED_ID,
                        color="secondary",
                    ),
                    dbc.Button(
                        "Confirm",
                        id=RESET_CONFIRM_BUTTON_SHARED_ID,
                        color="danger",
                    ),
                ]
            ),
        ],
        id=RESET_CONFIRM_MODAL_SHARED_ID,
        is_open=False,
        centered=True,
    )
    return [modal, dcc.Store(id=RESET_JOB_STORE_SHARED_ID)]


# Dash raises DuplicateCallback if the same callback is registered twice, and
# `app.layout` may be a callable that Dash invokes per request.
_reset_callbacks_registered = False


def register_reset_callbacks():
    """Register the job-reset callbacks (idempotent)."""
    global _reset_callbacks_registered
    if _reset_callbacks_registered:
        return
    _reset_callbacks_registered = True

    @callback(
        Output(RESET_CONFIRM_MODAL_SHARED_ID, "is_open", allow_duplicate=True),
        Output(RESET_BODY_DIV_SHARED_ID, "children"),
        Input(RESET_JOB_STORE_SHARED_ID, "data"),
        prevent_initial_call=True,
    )
    def open_reset_modal(store_data):
        """Open the reset confirmation modal when the store receives data."""
        if store_data is None:
            return False, dash.no_update
        return True, reset_message(store_data["action"])

    @callback(
        Output(RESET_CONFIRM_MODAL_SHARED_ID, "is_open", allow_duplicate=True),
        Output(URL_LOCATION_SHARED_ID, "href", allow_duplicate=True),
        Output(RESET_JOB_STORE_SHARED_ID, "data", allow_duplicate=True),
        Output(LOADING_OVERLAY_MODAL_SHARED_ID, "is_open", allow_duplicate=True),
        Input(RESET_CONFIRM_BUTTON_SHARED_ID, "n_clicks"),
        Input(RESET_CANCEL_BUTTON_SHARED_ID, "n_clicks"),
        State(RESET_JOB_STORE_SHARED_ID, "data"),
        prevent_initial_call=True,
    )
    def handle_reset_confirm(confirm_clicks, cancel_clicks, store_data):
        """Handle confirm/cancel on the reset modal."""
        triggered_ids = {
            t["prop_id"].split(".")[0]
            for t in callback_context.triggered
            if t["value"] is not None
        }

        if RESET_CANCEL_BUTTON_SHARED_ID in triggered_ids:
            return False, dash.no_update, None, dash.no_update

        if RESET_CONFIRM_BUTTON_SHARED_ID in triggered_ids:
            path = reset_job(store_data["job_id"], store_data["action"])
            return False, path, None, False

        return dash.no_update, dash.no_update, dash.no_update, dash.no_update
