"""Test the job reset protocol: exactly two actions, anything else is an error.

Until v0.13.0 the framework handled the reset and let any action it did not know
fall through to a plain reset, which is how ``"change_input"`` worked without
ever being named. The protocol is explicit now.
"""

import pytest

from csv_profiler.job_reset import (
    CHANGE_INPUT_ACTION,
    RESUBMIT_ACTION,
    reset_job,
    reset_message,
)


def test_unknown_action_is_not_reset():
    """A typo in an action must not silently reset (and wipe) the job."""
    with pytest.raises(ValueError, match="reset"):
        reset_job("any_job_id", "reset")


def test_unknown_action_gets_no_confirmation_text():
    """The modal never asks the user to confirm an action nobody handles."""
    with pytest.raises(ValueError, match="reset"):
        reset_message("reset")


@pytest.mark.parametrize("action", [RESUBMIT_ACTION, CHANGE_INPUT_ACTION])
def test_known_actions_have_a_confirmation_text(action):
    """Both actions say that results are deleted before the user confirms."""
    assert "delete all results" in reset_message(action)
