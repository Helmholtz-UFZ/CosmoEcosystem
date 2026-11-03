"""Test the job reset protocol: exactly two actions, anything else is an error.

Until v0.13.0 the framework handled the reset and let any action it did not know
fall through to a plain reset, which is how ``"change_input"`` worked without
ever being named. The protocol is explicit now.
"""

import pytest

from cosmo_ecosystem import job_log, job_run
from cosmo_ecosystem.job import Job
from cosmo_ecosystem.job_persistence import delete_job, load_row, update_columns

from csv_profiler.pydantic_models import ProfileConfig
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


@pytest.mark.parametrize("action", [RESUBMIT_ACTION, CHANGE_INPUT_ACTION])
def test_a_running_job_is_not_reset_and_not_resubmitted(monkeypatch, action):
    """The confirmation modal on a stale page cannot strand or restart a live run."""
    submitted = []
    monkeypatch.setattr(Job, "config_model", ProfileConfig)
    monkeypatch.setattr(Job, "file_validator", None)
    monkeypatch.setattr(
        Job,
        "submit_handler",
        staticmethod(lambda job: submitted.append(job) or ("t", False)),
    )
    job_id = f"test_reset_running_{action}"
    Job(new_job_id=job_id)
    job_run.mark_queued(job_id)
    before = load_row(job_id)

    try:
        assert reset_job(job_id, action) is None

        assert load_row(job_id) == before
        assert submitted == []
    finally:
        job_log.clear(job_id)
        update_columns(job_id, {"status": "FAILED"})
        delete_job(job_id)


def test_a_finished_job_is_reset_and_the_path_to_go_to_is_returned(monkeypatch):
    """A reset that applies still returns where to go."""
    monkeypatch.setattr(Job, "config_model", ProfileConfig)
    monkeypatch.setattr(Job, "file_validator", None)
    job_id = "test_reset_finished_job"
    Job(new_job_id=job_id)
    update_columns(job_id, {"status": "COMPLETED"})

    try:
        assert reset_job(job_id, CHANGE_INPUT_ACTION) == f"/input/{job_id}"

        assert load_row(job_id)["status"] == "PENDING"
    finally:
        delete_job(job_id)
