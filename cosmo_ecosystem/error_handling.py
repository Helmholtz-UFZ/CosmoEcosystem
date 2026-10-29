"""Error handling utilities for Dash apps."""

import json
import logging
import traceback
from collections.abc import Callable

import dash
import dash_bootstrap_components as dbc
import psycopg2
from dash import set_props
from sqlalchemy.exc import DatabaseError, OperationalError
from werkzeug.exceptions import NotFound

from cosmo_ecosystem.constants import (
    ERROR_MESSAGE_DIV_SHARED_ID,
    ERROR_MODAL_SHARED_ID,
    ERROR_TITLE_DIV_SHARED_ID,
    LOADING_OVERLAY_MODAL_SHARED_ID,
)
from cosmo_ecosystem.object_storage_manager import ObjectStorageError

log = logging.getLogger(__name__)


class InvalidJobID(Exception):
    """Raised by Job if init with invalid job id."""

    def __init__(self, job_id):
        """Add job id as attribute and format error message."""
        self.job_id = job_id
        super().__init__(f"{job_id} is not a valid job_id.")


class JobExists(Exception):
    """Raised by Job if a new job is created with an existing job id."""

    def __init__(self, job_id):
        """Add job id as attribute and format error message."""
        self.job_id = job_id
        super().__init__(f"{job_id} already exists.")


class JobNotFound(Exception):
    """Custom exception for when a job is not found."""

    def __init__(self, job_id):
        """Add job id as attribute and format error message."""
        self.job_id = job_id
        super().__init__(f"Job with ID '{job_id}' not found")


class JobCleanupFailed(Exception):
    """Raised after a cleanup run in which some expired jobs could not be deleted.

    The run has already deleted every other expired job; the failed ones keep
    their row, so the next run retries them.
    """

    def __init__(self, job_ids):
        """Add the failed job ids as attribute and format error message."""
        self.job_ids = job_ids
        super().__init__(
            f"Could not delete the jobs {', '.join(job_ids)}. They are kept and "
            "the next cleanup tries again."
        )


class JobDeletionFailed(Exception):
    """Raised after deleting several jobs, when some of them could not be deleted.

    Every other job was deleted; the failed ones keep their row and can be
    deleted again.
    """

    def __init__(self, job_ids):
        """Add the failed job ids as attribute and format error message."""
        self.job_ids = job_ids
        super().__init__(
            f"Could not delete the jobs {', '.join(job_ids)}. They are kept; "
            "try deleting them again."
        )


class WorkerManagementError(Exception):
    """Base exception for worker management operations."""

    ...


class TaskNotFoundError(WorkerManagementError):
    """Raised when task cannot be found."""

    ...


class WorkerNotAvailableError(WorkerManagementError):
    """Raised when no workers are available."""

    ...


class RedisConnectionError(WorkerManagementError):
    """Raised when Redis/Celery broker is unavailable."""

    ...


class FileValidationError(Exception):
    """Raised when an uploaded file fails validation."""

    ...


class JobTableNotConfigured(Exception):
    """Raised when a job method runs before ``DbManager.job_table`` is set.

    The assignment must be made on ``DbManager`` itself, not on a subclass —
    see docs/conventions/database_schema.md.
    """

    def __init__(self):
        """Format the error message with a pointer to the fix."""
        super().__init__(
            "DbManager.job_table is not set — the application must assign its "
            "own JobColumns subclass (via `DbManager.job_table = <YourJobTable>`) "
            "on DbManager itself before any job method runs."
        )


class JobLinkNotConfigured(Exception):
    """Raised when the job management page is imported before its link seam is set.

    Raised at import time, not in a callback, so it never reaches the error modal:
    the app does not start. See docs/conventions/framework_page_imports.md.
    """

    def __init__(self):
        """Format the error message with a pointer to the fix."""
        super().__init__(
            "cosmo_ecosystem.pages.job_link is not set — the application must "
            "assign a callable (job_id: str, row: dict) -> str to it before "
            "importing cosmo_ecosystem.pages.job_management. Assign the package "
            "attribute; `from cosmo_ecosystem.pages import job_link` binds a copy."
        )


USE_ERROR_MESSAGE = "use_error_message"
"""Sentinel message: show ``str(error)`` to the user instead of a fixed text.

Put it in the *message* slot of a response-table entry when the exception
already carries the sentence the user needs to read — a parser saying which
column of their file is malformed, for example. Without it there is no way to
pass such a message through: every other entry is a constant written long
before the error happened.

It belongs to the table, not to the app that fills one in, which is why it is
exported from here.
"""

EXPECTED_ERRORS = (
    NotFound,
    JobNotFound,
    InvalidJobID,
)
"""Exceptions the framework treats as normal user states.

They get the modal but no traceback and no ``on_unhandled`` call. An app whose
set differs passes its own tuple as ``expected_errors``; see ``handle_error``.
"""

database_error_title = "Database Connection Error"
database_error_message = "Unfortunately, it is not possible to connect to the job database. Please try again later."  # noqa
error_responds_dict = {
    psycopg2.DatabaseError: (
        database_error_title,
        database_error_message,
    ),
    DatabaseError: (
        database_error_title,
        database_error_message,
    ),
    OperationalError: (
        database_error_title,
        database_error_message,
    ),
    ObjectStorageError: (
        database_error_title,
        database_error_message,
    ),
    NotFound: ("File Not Found", "The file could not be found."),
    Exception: ("Internal Error", "Ups this should not happen. An error occurred."),
    JobNotFound: (
        "Job Not Found",
        "Could not find the job '{job_id}'. Visit job submission to make a new submission.",
    ),
    InvalidJobID: (
        "Job Not Found",
        "Could not find the job '{job_id}'. Visit job submission to make a new submission.",
    ),
    JobCleanupFailed: ("Cleanup Incomplete", USE_ERROR_MESSAGE),
    JobDeletionFailed: ("Deletion Incomplete", USE_ERROR_MESSAGE),
    WorkerNotAvailableError: (
        "No Workers Available",
        "No Celery workers are currently running. Please check the worker service status.",  # noqa
    ),
    TaskNotFoundError: (
        "Task Not Found",
        "The selected task could not be found. It may have already completed or been cancelled.",  # noqa
    ),
    RedisConnectionError: (
        "Background Service Unavailable",
        "The background job service is temporarily unavailable. Please try again later.",  # noqa
    ),
    JobExists: (
        "Job Already Exists",
        "A job with ID '{job_id}' already exists. Please use a different job ID.",
    ),
    # FileValidationError is always caught by the upload callback and shown
    # inline. If it reaches the global handler, something is wrong — treat
    # it as undefined behaviour and show the generic internal error.
    FileValidationError: (
        "Internal Error",
        "Ups this should not happen. An error occurred.",
    ),
}
"""Framework response table: exception type -> (modal title, modal message).

**Never mutate this from outside the framework.** An app that needs its own
entries passes them to ``handle_error`` as ``error_responses``; they are laid
over this table for the duration of the call and this dict stays untouched.

Mutating it works today only because ``handle_error`` happens to read the module
attribute on every call. It is a workaround for a missing seam, and it breaks
silently the moment the framework copies the table, caches it, or an app's
``import`` lands after the first error — none of which would raise anything.
The message slot accepts ``USE_ERROR_MESSAGE`` to show ``str(error)``.
"""

error_modal = dbc.Modal(
    [
        dbc.ModalHeader(
            dbc.ModalTitle("Error"),
            id=ERROR_TITLE_DIV_SHARED_ID,
            close_button=False,
            className="bg-light",
        ),
        dbc.ModalBody(id=ERROR_MESSAGE_DIV_SHARED_ID, className="text-danger bg-light"),
        dbc.ModalFooter(className="bg-light"),
    ],
    id=ERROR_MODAL_SHARED_ID,
    is_open=False,
)


def _truncate_string(value, max_length=200, head_length=100, tail_length=50):
    """Truncate a string if it exceeds max_length."""
    if not isinstance(value, str):
        return value
    if len(value) <= max_length:
        return value
    return f"{value[:head_length]}...{value[-tail_length:]}"


def _truncate_data(data):
    """Recursively truncate long strings in data structures."""
    if isinstance(data, dict):
        return {key: _truncate_data(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [_truncate_data(item) for item in data]
    elif isinstance(data, str):
        return _truncate_string(data)
    else:
        return data


def handle_error(
    error,
    *,
    on_unhandled: Callable[[Exception], None] | None = None,
    error_responses: dict[type[Exception], tuple[str, str]] | None = None,
    expected_errors: tuple[type[Exception], ...] | None = None,
) -> None:
    """Handle the error, show it in the modal, and optionally report it.

    Args:
        error: The exception Dash caught.
        on_unhandled: Called with the exception for errors outside the expected
            set — the same ones that get a full traceback logged. Both apps mail
            their maintainer from here.

            Keyword-only on purpose: ``handle_error(e)`` and
            ``Dash(on_error=handle_error)`` keep working unchanged, which is
            what makes this addition safe for a consumer still pinned to an
            older tag. An app wires its hook with a partial::

                Dash(..., on_error=partial(handle_error, on_unhandled=notify))

            The framework never imports an email service itself: that would pull
            mail configuration into the framework's dependencies and close an
            import cycle back into the app. It only calls what it is handed.
        error_responses: Entries laid **over** ``error_responds_dict`` for this
            call — the app supplies only its own exception types and the
            framework entries it wants to reword. Overlay rather than
            replacement, so an app never has to restate the database and job
            entries it is happy with.

            It exists because no framework entry can ever match an exception the
            framework cannot import. COSMOPOLITAN's ``FileValidationError``
            comes from ``soil_moisture_prediction.input_file_parser``: a
            different class from ``cosmo_ecosystem.error_handling.FileValidationError``
            that happens to share its name, so the framework's entry is not a
            worse match for it — it is no match at all.

            Use ``USE_ERROR_MESSAGE`` as the message to show ``str(error)``.
        expected_errors: **Replaces** ``EXPECTED_ERRORS`` when given, and does
            not extend it. An app must be able to take an entry *out* as well as
            put one in; the framework's three are a default, not a floor.

            What "expected" buys an exception: the modal, and nothing else — no
            traceback in the log, no ``on_unhandled`` call. COSMOPOLITAN counts
            six, three of them ordinary user states that would otherwise mail
            the maintainer on every single occurrence.

    Both keyword arguments default to the framework's own values, so
    ``handle_error(error)`` behaves exactly as it did in v0.6.2. That is pinned
    by a test: a consumer re-pinning to this version must not be able to notice.
    """
    log.debug(f"Error: {error}")

    responses = error_responds_dict
    if error_responses is not None:
        # A copy per call. The app's entries must not leak into the module table
        # and reach the next app in the same process — nor into the next call.
        responses = {**error_responds_dict, **error_responses}

    expected = EXPECTED_ERRORS if expected_errors is None else expected_errors

    if not isinstance(error, expected):
        callback_context = dash.ctx
        truncated_triggered = _truncate_data(callback_context.triggered)
        log.error(f"Unhandled error: {error}")
        log.error(
            f"Traceback info: {traceback.format_exc()}\n\n"
            f"Input info: {json.dumps(truncated_triggered)}"
        )
        if on_unhandled is not None:
            # Convention deviation (CLAUDE.md: no bare `except Exception`). The
            # hook is app code, typically an SMTP send, and it must not be able
            # to take the error modal down with it: a notification failing is no
            # reason to hide the error it was reporting from the user.
            try:
                on_unhandled(error)
            except Exception as hook_error:
                log.error(
                    f"on_unhandled hook failed: {hook_error}",
                    exc_info=True,
                )

    # dispatch lookup by exact type: an exception type that is not mapped falls
    # back to the generic Exception entry. A subclass of a mapped type does not
    # inherit its entry — this is a lookup, not an isinstance walk.
    error_type = type(error)
    if error_type not in responses:
        error_type = Exception
    error_title, error_message = responses[error_type]

    if error_message == USE_ERROR_MESSAGE:
        # No .format() on this branch: the text comes from the exception, not
        # from the table, and a parser message is free to contain braces.
        error_message = str(error)
    else:
        try:
            error_message = error_message.format(job_id=error.job_id)
        except AttributeError:
            pass

    log.error(f"{error_title}: {error_message}")
    log.error(f"Error details: {traceback.format_exc()}")
    set_props(LOADING_OVERLAY_MODAL_SHARED_ID, {"is_open": False})
    set_props(ERROR_MODAL_SHARED_ID, {"is_open": True})
    set_props(ERROR_TITLE_DIV_SHARED_ID, {"children": error_title})
    set_props(ERROR_MESSAGE_DIV_SHARED_ID, {"children": error_message})
