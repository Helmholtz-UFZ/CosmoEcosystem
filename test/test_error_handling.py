"""Tests for the three seams on ``handle_error``.

``on_unhandled`` lets an app be notified about unexpected errors — both apps mail
their maintainer — without the framework importing an email service.
``error_responses`` and ``expected_errors`` let an app bring its own table and
its own set of normal user states.

All three guard failures that are silent: swapping an app's own ``handle_error``
for the framework's switches its maintainer mails off, turns its ordinary user
states into pages, and shows "Internal Error" for exceptions the framework has
never heard of — with no import error and no failing test anywhere. Which is why
the behaviour is pinned down here.
"""

import pytest
from dash._callback_context import context_value
from dash._utils import AttributeDict
from werkzeug.exceptions import NotFound

from cosmo_ecosystem.constants import (
    ERROR_MESSAGE_DIV_SHARED_ID,
    ERROR_MODAL_SHARED_ID,
    ERROR_TITLE_DIV_SHARED_ID,
)
from cosmo_ecosystem.error_handling import (
    EXPECTED_ERRORS,
    USE_ERROR_MESSAGE,
    InvalidJobID,
    JobExists,
    JobNotFound,
    error_responds_dict,
    handle_error,
)


class ForeignFileValidationError(Exception):
    """Stand-in for an exception class the framework cannot import.

    COSMOPOLITAN's ``FileValidationError`` comes from
    ``soil_moisture_prediction.input_file_parser`` — a different class from the
    framework's, sharing only the name. No framework table entry can ever match
    it, which is the whole reason ``error_responses`` exists.
    """


class Recorder:
    """Callable that records the exceptions it was handed."""

    def __init__(self, raises=None):
        """Store an optional exception the recorder raises when called."""
        self.calls = []
        self.raises = raises

    def __call__(self, error):
        """Record the error, then raise if this recorder was built to fail."""
        self.calls.append(error)
        if self.raises is not None:
            raise self.raises


@pytest.fixture
def callback_ctx():
    """Install the Dash callback context ``handle_error`` runs inside.

    Dash calls ``on_error`` from within a callback, where ``dash.ctx`` and
    ``set_props`` are available; outside one both raise
    MissingCallbackContextException. The fixture provides the same context Dash
    would and yields it, so a test can assert on the props that were set.
    """
    ctx = AttributeDict(triggered_inputs=[], updated_props={})
    token = context_value.set(ctx)
    yield ctx
    context_value.reset(token)


def test_hook_called_for_unexpected_error(callback_ctx):
    """An error outside the expected set reaches the hook."""
    notify = Recorder()
    error = ValueError("something nobody planned for")

    handle_error(error, on_unhandled=notify)

    assert notify.calls == [error]


@pytest.mark.parametrize(
    "error",
    [JobNotFound("no_such_job"), InvalidJobID("../etc/passwd"), NotFound()],
)
def test_hook_not_called_for_expected_errors(callback_ctx, error):
    """Errors the app handles by design must not page the maintainer."""
    notify = Recorder()

    handle_error(error, on_unhandled=notify)

    assert notify.calls == []


def test_expected_error_still_opens_the_modal(callback_ctx):
    """Skipping the hook does not skip the user-facing modal."""
    handle_error(JobNotFound("no_such_job"), on_unhandled=Recorder())

    assert callback_ctx.updated_props[ERROR_MODAL_SHARED_ID]["is_open"] is True
    assert callback_ctx.updated_props[ERROR_TITLE_DIV_SHARED_ID]["children"] == (
        "Job Not Found"
    )


def test_without_hook_behaves_as_before(callback_ctx):
    """The v0.4.1 call signature keeps working — the parameter is additive."""
    handle_error(ValueError("boom"))

    assert callback_ctx.updated_props[ERROR_MODAL_SHARED_ID]["is_open"] is True
    assert callback_ctx.updated_props[ERROR_TITLE_DIV_SHARED_ID]["children"] == (
        "Internal Error"
    )


def test_dispatch_is_by_exact_type_not_isinstance(callback_ctx):
    """A subclass of a mapped exception falls back to the generic entry.

    The lookup is a dict hit on ``type(error)``, never an isinstance walk, so a
    subclass does not inherit its parent's title. Pinned because it is the kind
    of thing a later refactor changes by accident: a mapped subclass would start
    reporting a different modal title with nothing else failing.
    """

    class UnmappedJobNotFound(JobNotFound):
        pass

    handle_error(UnmappedJobNotFound("no_such_job"))

    assert callback_ctx.updated_props[ERROR_TITLE_DIV_SHARED_ID]["children"] == (
        "Internal Error"
    )


def test_failing_hook_does_not_swallow_the_modal(callback_ctx):
    """A broken notifier must not hide the error it was reporting."""
    notify = Recorder(raises=RuntimeError("SMTP unreachable"))

    handle_error(ValueError("boom"), on_unhandled=notify)

    assert notify.calls  # the hook did run
    assert callback_ctx.updated_props[ERROR_MODAL_SHARED_ID]["is_open"] is True
    assert ERROR_MESSAGE_DIV_SHARED_ID in callback_ctx.updated_props


# ---------------------------------------------------------------------------
# The re-pin guarantee: `handle_error(error)` is v0.6.2, argument for argument
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "error, title, message",
    [
        (
            ValueError("boom"),
            "Internal Error",
            "Ups this should not happen. An error occurred.",
        ),
        (NotFound(), "File Not Found", "The file could not be found."),
        (
            JobNotFound("quiet_amber_otter"),
            "Job Not Found",
            "Could not find the job 'quiet_amber_otter'. "
            "Visit job submission to make a new submission.",
        ),
        (
            InvalidJobID("../etc/passwd"),
            "Job Not Found",
            "Could not find the job '../etc/passwd'. "
            "Visit job submission to make a new submission.",
        ),
        (
            JobExists("quiet_amber_otter"),
            "Job Already Exists",
            "A job with ID 'quiet_amber_otter' already exists. "
            "Please use a different job ID.",
        ),
    ],
)
def test_bare_call_is_unchanged_from_v0_6_2(callback_ctx, error, title, message):
    """``handle_error(error)`` with no keywords must still be v0.6.2 exactly.

    This is the condition under which COSMONAUT can re-pin to v0.7.0 without
    noticing. Both new keywords default to the framework's own values, so the
    modal text for every entry in the table has to come out byte for byte as
    before — that is what this pins, per entry rather than by spot check.
    """
    handle_error(error)

    assert callback_ctx.updated_props[ERROR_TITLE_DIV_SHARED_ID]["children"] == title
    assert (
        callback_ctx.updated_props[ERROR_MESSAGE_DIV_SHARED_ID]["children"] == message
    )


def test_default_expected_set_is_the_v0_6_2_three():
    """The set an omitted ``expected_errors`` falls back to has not moved.

    Adding a fourth entry here silently stops a maintainer mail; removing one
    silently starts sending mail for an ordinary user state. Neither shows up
    anywhere else.
    """
    assert EXPECTED_ERRORS == (NotFound, JobNotFound, InvalidJobID)


# ---------------------------------------------------------------------------
# `error_responses` — laid over the table, never instead of it
# ---------------------------------------------------------------------------


def test_error_responses_reaches_a_class_the_framework_cannot_import(callback_ctx):
    """The case the seam exists for: a foreign exception class.

    COSMOPOLITAN's parser raises its own ``FileValidationError``. It is not a
    subclass of the framework's, so no framework entry can match it and the user
    would be shown "Internal Error" for a file they can actually fix.
    """
    handle_error(
        ForeignFileValidationError("column 3 is not numeric"),
        error_responses={
            ForeignFileValidationError: ("Invalid File", "Please check your file.")
        },
    )

    assert callback_ctx.updated_props[ERROR_TITLE_DIV_SHARED_ID]["children"] == (
        "Invalid File"
    )


def test_error_responses_keeps_the_framework_entries(callback_ctx):
    """Overlay, not replacement — the app restates nothing it is happy with."""
    handle_error(
        JobNotFound("quiet_amber_otter"),
        error_responses={
            ForeignFileValidationError: ("Invalid File", "Please check your file.")
        },
    )

    assert callback_ctx.updated_props[ERROR_TITLE_DIV_SHARED_ID]["children"] == (
        "Job Not Found"
    )


def test_error_responses_can_override_a_framework_entry(callback_ctx):
    """An app may reword an entry it does not like without forking the table."""
    handle_error(
        JobNotFound("quiet_amber_otter"),
        error_responses={
            JobNotFound: ("Unbekannter Job", "Job '{job_id}' gibt es nicht.")
        },
    )

    assert callback_ctx.updated_props[ERROR_TITLE_DIV_SHARED_ID]["children"] == (
        "Unbekannter Job"
    )
    assert callback_ctx.updated_props[ERROR_MESSAGE_DIV_SHARED_ID]["children"] == (
        "Job 'quiet_amber_otter' gibt es nicht."
    )


def test_error_responses_does_not_mutate_the_module_table(callback_ctx):
    """The overlay lives for one call.

    COSMONAUT used to reach into ``error_responds_dict`` and ``.update()`` it,
    which is the workaround this argument replaces. If the argument leaked back
    into the module dict it would be the same bug with a nicer spelling.
    """
    before = dict(error_responds_dict)

    handle_error(
        ForeignFileValidationError("column 3 is not numeric"),
        error_responses={
            ForeignFileValidationError: ("Invalid File", "Please check your file."),
            JobNotFound: ("Overridden", "Overridden"),
        },
    )

    assert error_responds_dict == before

    handle_error(JobNotFound("quiet_amber_otter"))
    assert callback_ctx.updated_props[ERROR_TITLE_DIV_SHARED_ID]["children"] == (
        "Job Not Found"
    )


# ---------------------------------------------------------------------------
# `expected_errors` — replaces the set, in both directions
# ---------------------------------------------------------------------------


def test_expected_errors_adds_an_app_state_to_the_quiet_set(callback_ctx):
    """An app's own ordinary user state stops paging the maintainer."""
    notify = Recorder()

    handle_error(
        ForeignFileValidationError("column 3 is not numeric"),
        on_unhandled=notify,
        expected_errors=EXPECTED_ERRORS + (ForeignFileValidationError,),
    )

    assert notify.calls == []


def test_expected_errors_replaces_rather_than_extends(callback_ctx):
    """An app must be able to take an entry out, not only put one in.

    ``JobNotFound`` is expected by the framework. An app that passes a set
    without it wants to hear about it — if the argument merely extended the
    framework's tuple there would be no way to say so.
    """
    notify = Recorder()
    error = JobNotFound("quiet_amber_otter")

    handle_error(error, on_unhandled=notify, expected_errors=(NotFound,))

    assert notify.calls == [error]


def test_empty_expected_errors_means_nothing_is_expected(callback_ctx):
    """``()`` is a set, not a missing argument.

    The check has to be ``is None``; a truthiness test would read an empty tuple
    as "not given" and quietly restore the framework's three.
    """
    notify = Recorder()
    error = NotFound()

    handle_error(error, on_unhandled=notify, expected_errors=())

    assert notify.calls == [error]


# ---------------------------------------------------------------------------
# The `USE_ERROR_MESSAGE` sentinel
# ---------------------------------------------------------------------------


def test_sentinel_shows_the_exception_text(callback_ctx):
    """A table entry may defer to the exception's own message.

    Without this there is no way at all to get a parser's sentence — the one
    thing that tells the user which column of their file is wrong — in front of
    them; every other entry is a constant written long before the error.
    """
    handle_error(
        ForeignFileValidationError("column 3 is not numeric"),
        error_responses={
            ForeignFileValidationError: ("Invalid File", USE_ERROR_MESSAGE)
        },
    )

    assert callback_ctx.updated_props[ERROR_TITLE_DIV_SHARED_ID]["children"] == (
        "Invalid File"
    )
    assert callback_ctx.updated_props[ERROR_MESSAGE_DIV_SHARED_ID]["children"] == (
        "column 3 is not numeric"
    )


def test_sentinel_message_is_not_run_through_format(callback_ctx):
    """Braces in a parser message must survive.

    Table messages go through ``str.format`` for ``{job_id}``. An exception text
    is not a template — a message mentioning a ``{"key": …}`` fragment would
    raise KeyError inside the error handler, which is the worst possible place
    to raise.
    """
    handle_error(
        ForeignFileValidationError('unexpected token {"unit": "mm"} in row 4'),
        error_responses={
            ForeignFileValidationError: ("Invalid File", USE_ERROR_MESSAGE)
        },
    )

    assert callback_ctx.updated_props[ERROR_MESSAGE_DIV_SHARED_ID]["children"] == (
        'unexpected token {"unit": "mm"} in row 4'
    )
