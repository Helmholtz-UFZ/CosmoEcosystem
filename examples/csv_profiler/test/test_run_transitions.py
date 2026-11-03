"""Test the framework's named status transitions against a real Postgres.

Every transition is one conditional update that says whether it applied (ADR
0005). The tests assert what ends up in the row and the job log. "Overtaken" and
"stale" are built with real calls and SQL, never with mocks.
"""

import datetime
import time
import uuid

import pytest

from cosmo_ecosystem import job_log, job_run
from cosmo_ecosystem.db_manager import DbManager
from cosmo_ecosystem.error_handling import JobNotFound
from cosmo_ecosystem.job_persistence import load_row

# Wires DbManager.job_table exactly as the worker process has it.
import csv_profiler.domain  # noqa: F401
from job_row_helpers import drop_row, row_and_log, set_heartbeat

CANCELLED_LINE = "cancelled"


def _create(job_id, status, submitted=False):
    """Create job_id in the given status, with the traces of an earlier run."""
    DbManager.add_entry(
        {
            "job_id": job_id,
            "start_date": datetime.date.today(),
            "input_data": "{}",
            "submitted": submitted,
            "notified_end": False,
            "status": status,
            "version": "0.1.0",
        }
    )


def _leave_traces_of_a_run(job_id):
    """Give the row the heartbeat and run id a run that claimed it left behind."""
    set_heartbeat(job_id, "3 minutes")
    DbManager.update_column(job_id, {"run_id": uuid.uuid4()})


@pytest.fixture
def jobs():
    """Create the jobs a test names; delete them and their job logs afterwards."""
    created = []

    def create(job_id, status, submitted=False):
        _create(job_id, status, submitted)
        created.append(job_id)
        return job_id

    yield create
    for job_id in created:
        job_log.clear(job_id)
        drop_row(job_id)


@pytest.mark.parametrize("status", ["PENDING", "FAILED"])
def test_queueing_a_pending_or_failed_job_queues_the_run(jobs, status):
    """The submit guard: RUNNING, no heartbeat, no run id, and submitted."""
    job_id = jobs(f"test_transitions_queue_{status.lower()}", status)
    _leave_traces_of_a_run(job_id)

    assert job_run.mark_queued(job_id) is True

    row = load_row(job_id)
    assert (row["status"], row["heartbeat_at"], row["run_id"], row["submitted"]) == (
        "RUNNING",
        None,
        None,
        True,
    )


@pytest.mark.parametrize("status", ["RUNNING", "COMPLETED"])
def test_queueing_a_running_or_completed_job_changes_nothing(jobs, status):
    """The guard is lost: the row, with its live run's traces, stays as it is."""
    job_id = jobs(f"test_transitions_queue_refused_{status.lower()}", status)
    _leave_traces_of_a_run(job_id)
    before = load_row(job_id)

    assert job_run.mark_queued(job_id) is False

    assert load_row(job_id) == before


def test_a_second_queueing_returns_false_and_changes_nothing(jobs):
    """Two clicks on Submit queue one run."""
    job_id = jobs("test_transitions_queue_twice", "PENDING")

    first = job_run.mark_queued(job_id)
    after_first = load_row(job_id)
    second = job_run.mark_queued(job_id)

    assert (first, second) == (True, False)
    assert load_row(job_id) == after_first


@pytest.mark.parametrize("status", ["PENDING", "FAILED", "COMPLETED"])
@pytest.mark.parametrize("submitted", [True, False])
def test_a_reset_returns_a_job_to_pending_and_keeps_its_submitted_mark(
    jobs, status, submitted
):
    """A reset clears the run's traces; "submitted at least once" stays."""
    job_id = jobs(
        f"test_transitions_reset_{status.lower()}_{submitted}", status, submitted
    )
    _leave_traces_of_a_run(job_id)

    assert job_run.mark_pending(job_id) is True

    row = load_row(job_id)
    assert (row["status"], row["heartbeat_at"], row["run_id"], row["submitted"]) == (
        "PENDING",
        None,
        None,
        submitted,
    )


def test_a_reset_is_refused_while_a_run_is_running(jobs):
    """A reset cannot strand a live run: the row keeps its heartbeat and run id."""
    job_id = jobs("test_transitions_reset_running", "RUNNING", True)
    _leave_traces_of_a_run(job_id)
    before = load_row(job_id)

    assert job_run.mark_pending(job_id) is False

    assert load_row(job_id) == before


def test_cancelling_a_running_job_fails_it_and_says_so_in_the_job_log(jobs):
    """The run ends FAILED, and the job log tells why."""
    job_id = jobs("test_transitions_cancel_running", "RUNNING", True)
    _leave_traces_of_a_run(job_id)

    assert job_run.mark_cancelled(job_id) is True

    assert load_row(job_id)["status"] == "FAILED"
    assert CANCELLED_LINE in job_log.read(job_id)


@pytest.mark.parametrize("status", ["PENDING", "COMPLETED", "FAILED"])
def test_cancelling_a_job_that_is_not_running_changes_nothing(jobs, status):
    """A late click on Cancel leaves a finished result, and its job log, alone."""
    job_id = jobs(f"test_transitions_cancel_{status.lower()}", status, True)
    before = row_and_log(job_id), load_row(job_id)

    assert job_run.mark_cancelled(job_id) is False

    assert (row_and_log(job_id), load_row(job_id)) == before


def test_cancelling_a_job_without_a_row_raises_job_not_found():
    """Cancelling a deleted job fails loud, like the other transitions."""
    with pytest.raises(JobNotFound):
        job_run.mark_cancelled("test_transitions_cancel_no_row")


def _row_state(job_id):
    """Return the columns a run owns, as they are now."""
    row = load_row(job_id)
    return row["status"], row["heartbeat_at"], row["run_id"]


def _noop(job_id, work_dir):
    """A computation that does nothing."""


def test_a_run_claims_the_row_with_a_fresh_run_id(jobs):
    """Each claim gives its run an identity of its own."""
    job_id = jobs("test_transitions_claim_run_id", "PENDING")
    seen = []

    def compute(job_id, work_dir):
        seen.append(_row_state(job_id))

    job_run.mark_queued(job_id)
    job_run.run(job_id, compute)
    job_run.mark_pending(job_id)
    job_run.mark_queued(job_id)
    job_run.run(job_id, compute)

    (status_1, beat_1, run_1), (status_2, beat_2, run_2) = seen
    assert (status_1, status_2) == ("RUNNING", "RUNNING")
    assert beat_1 is not None and beat_2 is not None
    assert isinstance(run_1, uuid.UUID) and isinstance(run_2, uuid.UUID)
    assert run_1 != run_2


def _overtake(job_id):
    """Claim a run A, then cancel, reset, queue and claim again as run B.

    Real transitions only. Returns A's run id and B's run id.
    """
    job_run.mark_queued(job_id)
    run_a = DbManager.claim_run(job_id)
    assert job_run.mark_cancelled(job_id)
    assert job_run.mark_pending(job_id)
    assert job_run.mark_queued(job_id)
    run_b = DbManager.claim_run(job_id)
    assert run_a and run_b and run_a != run_b
    return run_a, run_b


def test_an_overtaken_runs_heartbeat_and_end_change_nothing(jobs):
    """Run A outlived its cancel; run B's row is not touched by A's writes."""
    job_id = jobs("test_transitions_overtaken_writes", "PENDING")
    run_a, run_b = _overtake(job_id)
    set_heartbeat(job_id, "30 seconds")
    before = row_and_log(job_id), _row_state(job_id)

    beat = DbManager.refresh_heartbeat(job_id, run_a)
    completed = DbManager.end_run(job_id, run_a, "COMPLETED")
    failed = DbManager.end_run(job_id, run_a, "FAILED")

    assert (beat, completed, failed) == (False, False, False)
    assert (row_and_log(job_id), _row_state(job_id)) == before
    assert _row_state(job_id)[2] == run_b


def test_the_own_run_beats_and_ends_the_row(jobs):
    """The run that holds the row refreshes it and writes its final status."""
    job_id = jobs("test_transitions_own_run", "PENDING")
    job_run.mark_queued(job_id)
    run_id = DbManager.claim_run(job_id)
    set_heartbeat(job_id, "30 seconds")
    stale = load_row(job_id)["heartbeat_at"]

    assert DbManager.refresh_heartbeat(job_id, run_id) is True
    assert load_row(job_id)["heartbeat_at"] > stale
    assert DbManager.end_run(job_id, run_id, "COMPLETED") is True
    assert load_row(job_id)["status"] == "COMPLETED"


def test_a_cancelled_run_cannot_end_the_row_it_no_longer_holds(jobs):
    """A write after the final status: the late COMPLETED does not undo the cancel."""
    job_id = jobs("test_transitions_end_after_cancel", "PENDING")
    job_run.mark_queued(job_id)
    run_id = DbManager.claim_run(job_id)
    job_run.mark_cancelled(job_id)

    assert DbManager.end_run(job_id, run_id, "COMPLETED") is False

    assert load_row(job_id)["status"] == "FAILED"


def test_a_run_that_is_overtaken_writes_no_final_status_and_reports_none(jobs):
    """`run` returns None when its end write applied to nothing, never COMPLETED."""
    job_id = jobs("test_transitions_overtaken_run", "PENDING")
    job_run.mark_queued(job_id)
    seen = {}

    def compute_while_overtaken(job_id, work_dir):
        """Cancel this run, then run B takes the row."""
        job_run.mark_cancelled(job_id)
        job_run.mark_pending(job_id)
        job_run.mark_queued(job_id)
        seen["run_b"] = DbManager.claim_run(job_id)
        seen["state_b"] = _row_state(job_id)
        time.sleep(0.8)  # four heartbeat intervals of run A

    result = job_run.run(job_id, compute_while_overtaken, heartbeat_interval=0.2)

    assert result is None
    assert _row_state(job_id) == seen["state_b"]
    assert seen["state_b"][2] == seen["run_b"]


def test_a_failing_run_that_is_overtaken_writes_no_failed_status(jobs):
    """The FAILED write of an overtaken run applies to nothing, too."""
    job_id = jobs("test_transitions_overtaken_failure", "PENDING")
    job_run.mark_queued(job_id)
    seen = {}

    def compute_then_fail(job_id, work_dir):
        job_run.mark_cancelled(job_id)
        job_run.mark_pending(job_id)
        job_run.mark_queued(job_id)
        DbManager.claim_run(job_id)
        seen["state_b"] = _row_state(job_id)
        raise RuntimeError("the old run dies late")

    result = job_run.run(job_id, compute_then_fail)

    assert result is None
    assert _row_state(job_id) == seen["state_b"]
