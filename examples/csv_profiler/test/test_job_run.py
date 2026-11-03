"""Test the framework's job run against real Postgres and S3 servers."""

import datetime
import logging
import os
import shutil
import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from cosmo_ecosystem import job_log, job_persistence, job_run, object_storage_manager
from cosmo_ecosystem.config import OBJECT_STORAGE_BUCKET, OBJECT_STORAGE_REMOTE_NAME
from cosmo_ecosystem.db_manager import DbManager
from cosmo_ecosystem.error_handling import JobNotFound
from cosmo_ecosystem.job_log import JobLogHandler
from cosmo_ecosystem.job_persistence import load_row, local_dir
from cosmo_ecosystem.tasks.sweep_tasks import sweep_lost_runs
from cosmo_ecosystem.object_storage_manager import (
    delete_directory_from_storage,
    get_remote_files,
    save_files,
)

# Wires the framework Job seams exactly as the worker process has them.
import csv_profiler.domain  # noqa: F401
from csv_profiler.pydantic_models import ProfileConfig
from csv_profiler.tasks.computation_tasks import profile
from job_row_helpers import row_and_log, set_heartbeat

SAMPLE_CSV = os.path.join(os.path.dirname(__file__), "sample_mixed.csv")
CSV_NAME = "sample_mixed.csv"

log = logging.getLogger(__name__)


def _submit(job_id, input_data=None):
    """Create job_id as submitted: its CSV in the remote prefix, its run queued."""
    if input_data is None:
        input_data = ProfileConfig(
            job_id=job_id, upload_file_name=CSV_NAME
        ).model_dump_json()
    os.makedirs(local_dir(job_id), exist_ok=True)
    shutil.copy(SAMPLE_CSV, os.path.join(local_dir(job_id), CSV_NAME))
    save_files(job_id)
    # Another pod ran the job: this one starts without a work dir.
    shutil.rmtree(local_dir(job_id))
    DbManager.add_entry(
        {
            "job_id": job_id,
            "start_date": datetime.date.today(),
            "input_data": input_data,
            "submitted": True,
            "notified_end": False,
            "status": "PENDING",
            "version": "0.1.0",
        }
    )
    job_run.mark_queued(job_id)


def _remote_files(job_id):
    """List the objects stored below job_id's remote prefix."""
    return get_remote_files(
        f"{OBJECT_STORAGE_REMOTE_NAME}:{OBJECT_STORAGE_BUCKET}/{job_id}"
    )


def _cleanup(job_id):
    """Remove whatever a test left behind for job_id."""
    delete_directory_from_storage(job_id)
    shutil.rmtree(local_dir(job_id), ignore_errors=True)
    job_log.clear(job_id)
    if DbManager.check_existence(job_id):
        DbManager.delete_job(job_id)


def test_a_successful_run_ends_completed_with_its_outputs_in_the_remote_prefix():
    """A COMPLETED row always points at results any pod can fetch."""
    job_id = "test_job_run_success"
    _submit(job_id)

    try:
        status = job_run.run(job_id, profile)

        assert status == "COMPLETED"
        assert load_row(job_id)["status"] == "COMPLETED"
        assert "result.json" in _remote_files(job_id)
    finally:
        _cleanup(job_id)


class _BrokenComputation(Exception):
    """Raised by a compute that fails on purpose."""


def _failing_compute(job_id, work_dir):
    """A computation that logs a step, then fails."""
    log.info(f"Computing job {job_id}")
    raise _BrokenComputation("the model diverged")


def test_a_failing_computation_ends_failed_with_its_traceback_in_the_job_log():
    """A dead job shows FAILED and why, and the Celery task itself succeeds."""
    job_id = "test_job_run_compute_fails"
    _submit(job_id)

    try:
        status = job_run.run(job_id, _failing_compute)

        assert status == "FAILED"
        assert load_row(job_id)["status"] == "FAILED"
        content = job_log.read(job_id)
        assert f"INFO in test_job_run: Computing job {job_id}" in content
        assert "Traceback (most recent call last)" in content
        assert "_BrokenComputation: the model diverged" in content
    finally:
        _cleanup(job_id)


def test_a_failing_upload_never_leaves_the_row_completed(monkeypatch):
    """The row is written after the upload, so it never points at missing files."""
    job_id = "test_job_run_upload_fails"
    _submit(job_id)

    def compute_then_lose_the_store(job_id, work_dir):
        """Write an output, then make the store unreachable for the upload."""
        with open(os.path.join(work_dir, "out.txt"), "w", encoding="UTF-8") as f:
            f.write("result\n")
        # rclone creates a missing bucket on upload, so an unknown remote is
        # what makes the upload fail for real (as in test_job_persistence).
        monkeypatch.setattr(
            object_storage_manager, "OBJECT_STORAGE_REMOTE_NAME", "no-such-remote"
        )

    try:
        status = job_run.run(job_id, compute_then_lose_the_store)

        assert status == "FAILED"
        assert load_row(job_id)["status"] == "FAILED"
        assert "ObjectStorageError" in job_log.read(job_id)
    finally:
        monkeypatch.undo()
        _cleanup(job_id)


def test_a_job_whose_input_cannot_be_loaded_ends_failed_with_the_reason():
    """A broken submission does not hang in RUNNING forever."""
    job_id = "test_job_run_load_fails"
    # Fewer histogram bins than ProfileConfig allows: loading the job raises.
    _submit(job_id, input_data=f'{{"job_id": "{job_id}", "histogram_bins": 1}}')

    try:
        status = job_run.run(job_id, profile)

        assert status == "FAILED"
        assert load_row(job_id)["status"] == "FAILED"
        content = job_log.read(job_id)
        assert "ValidationError" in content
        assert "histogram_bins" in content
        assert "UnboundLocalError" not in content
    finally:
        _cleanup(job_id)


def test_a_job_without_a_row_is_dropped_and_no_row_appears():
    """A task for a job deleted meanwhile is dropped instead of resurrecting it."""
    job_id = "test_job_run_no_row"

    try:
        status = job_run.run(job_id, _failing_compute)

        assert status is None
        assert not DbManager.check_existence(job_id)
        assert job_log.read(job_id) == ""
    finally:
        _cleanup(job_id)


def test_the_job_log_is_readable_while_the_computation_still_runs():
    """A user watches the log of a running job from whichever pod serves the page."""
    job_id = "test_job_run_live"
    _submit(job_id)
    seen = []

    def compute_waiting_for_its_own_log(job_id, work_dir):
        """Log a line, then wait until another connection can read it."""
        log.info("halfway there")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if "halfway there" in job_log.read(job_id):
                seen.append(True)
                return
            time.sleep(0.1)

    try:
        job_run.run(job_id, compute_waiting_for_its_own_log)

        assert seen == [True]
    finally:
        _cleanup(job_id)


def test_a_new_run_starts_with_an_empty_job_log():
    """After a resubmit the log shows the current run, never an old one."""
    job_id = "test_job_run_rerun"
    _submit(job_id)

    def computing(message):
        """Return a compute that logs message."""

        def compute(job_id, work_dir):
            log.info(message)

        return compute

    try:
        job_run.run(job_id, computing("first run"))
        job_run.mark_pending(job_id)
        job_run.mark_queued(job_id)
        job_run.run(job_id, computing("second run"))

        content = job_log.read(job_id)
        assert "second run" in content
        assert "first run" not in content
    finally:
        _cleanup(job_id)


def test_debug_records_reach_the_job_log_whatever_the_root_level(monkeypatch):
    """The run captures DEBUG even outside the worker's logging config."""
    job_id = "test_job_run_debug"
    _submit(job_id)
    root = logging.getLogger()
    monkeypatch.setattr(root, "level", logging.WARNING)

    def compute(job_id, work_dir):
        log.debug("a detail")

    try:
        job_run.run(job_id, compute)

        assert "DEBUG in test_job_run: a detail" in job_log.read(job_id)
        assert root.level == logging.WARNING
    finally:
        _cleanup(job_id)


def test_no_job_log_handler_is_left_on_the_root_logger():
    """The next task in the same worker does not write into this job's log."""
    job_id = "test_job_run_detach"
    _submit(job_id)

    try:
        job_run.run(job_id, lambda job_id, work_dir: None)
        after_success = _job_log_handlers()
        job_run.mark_queued(job_id)
        job_run.run(job_id, _failing_compute)
        after_failure = _job_log_handlers()

        assert (after_success, after_failure) == ([], [])
    finally:
        _cleanup(job_id)


def _job_log_handlers():
    """Return the JobLogHandlers attached to the root logger."""
    return [h for h in logging.getLogger().handlers if isinstance(h, JobLogHandler)]


def test_a_database_outage_in_the_job_log_does_not_fail_the_run(monkeypatch, caplog):
    """An hour-long computation is not lost to a logging hiccup, nor its log flooded."""
    job_id = "test_job_run_log_outage"
    _submit(job_id)
    unreachable = create_engine("postgresql+psycopg2://nobody:none@127.0.0.1:1/none")

    def compute_through_an_outage(job_id, work_dir):
        """Log while the database is down until a batch is dropped, then recover."""
        monkeypatch.setattr(DbManager, "_Session", sessionmaker(bind=unreachable))
        log.info("lost in the outage")
        deadline = time.monotonic() + 10
        while not _dropped(caplog) and time.monotonic() < deadline:
            time.sleep(0.1)
        monkeypatch.undo()
        log.info("after the outage")

    try:
        status = job_run.run(job_id, compute_through_an_outage)

        assert _dropped(caplog)
        assert status == "COMPLETED"
        assert load_row(job_id)["status"] == "COMPLETED"
        content = job_log.read(job_id)
        assert "after the outage" in content
        # The handler's own warning goes to the worker log only: buffered into
        # the job log, it would be retried with every failing batch.
        assert "Dropped" not in content
    finally:
        monkeypatch.undo()
        _cleanup(job_id)


def _dropped(caplog):
    """Return whether a JobLogHandler reported a dropped batch."""
    return any(
        record.name == "cosmo_ecosystem.job_log" and "Dropped" in record.getMessage()
        for record in caplog.records
    )


def test_a_job_log_that_cannot_be_cleared_ends_the_run_failed(monkeypatch):
    """A database hiccup at the very start does not leave the job RUNNING forever."""
    job_id = "test_job_run_clear_fails"
    _submit(job_id)

    def clear_fails(job_id):
        raise OperationalError("DELETE FROM job_logs", {}, Exception("hiccup"))

    monkeypatch.setattr(job_log, "clear", clear_fails)

    try:
        status = job_run.run(job_id, lambda job_id, work_dir: None)

        assert status == "FAILED"
        assert load_row(job_id)["status"] == "FAILED"
        assert _job_log_handlers() == []
    finally:
        monkeypatch.undo()
        _cleanup(job_id)


def test_a_run_with_the_database_down_returns_failed_and_tells_the_worker_log(
    monkeypatch, caplog
):
    """With nowhere to record FAILED, the run still ends and says so."""
    job_id = "test_job_run_database_down"
    unreachable = create_engine("postgresql+psycopg2://nobody:none@127.0.0.1:1/none")
    monkeypatch.setattr(DbManager, "_Session", sessionmaker(bind=unreachable))

    with caplog.at_level(logging.ERROR, logger="cosmo_ecosystem.job_run"):
        status = job_run.run(job_id, lambda job_id, work_dir: None)

    assert status == "FAILED"
    assert any(
        record.levelname == "ERROR"
        and job_id in record.getMessage()
        and "FAILED" in record.getMessage()
        for record in caplog.records
    )
    assert _job_log_handlers() == []


@pytest.mark.parametrize(
    "compute, final_status, last_record",
    [
        (lambda job_id, work_dir: log.info("last words"), "COMPLETED", "last words"),
        (_failing_compute, "FAILED", "_BrokenComputation: the model diverged"),
    ],
)
def test_whoever_sees_the_final_status_also_sees_the_last_records(
    monkeypatch, compute, final_status, last_record
):
    """A poll that shows the job finished also shows how it ended, traceback included."""
    job_id = "test_job_run_final_records"
    _submit(job_id)
    log_when_final = []
    end_run = DbManager.end_run

    def end_run_and_read_the_log(job_id, run_id, status):
        """Write the status, then read the job log as a poll would right then."""
        applied = end_run(job_id, run_id, status)
        if status == final_status:
            log_when_final.append(job_log.read(job_id))
        return applied

    monkeypatch.setattr(DbManager, "end_run", end_run_and_read_the_log)

    try:
        job_run.run(job_id, compute)

        assert len(log_when_final) == 1
        assert last_record in log_when_final[0]
    finally:
        monkeypatch.undo()
        _cleanup(job_id)


def test_mark_queued_makes_the_row_running_with_no_heartbeat():
    """A queued run is RUNNING, and no worker has claimed it yet."""
    job_id = "test_job_run_mark_queued"
    _submit(job_id)
    job_persistence.update_columns(job_id, {"status": "FAILED"})
    set_heartbeat(job_id, "11 minutes")

    try:
        job_run.mark_queued(job_id)

        row = load_row(job_id)
        assert (row["status"], row["heartbeat_at"]) == ("RUNNING", None)
    finally:
        _cleanup(job_id)


def test_a_second_delivery_of_a_live_run_is_dropped():
    """Two deliveries of one message never compute the same job twice."""
    job_id = "test_job_run_claimed_once"
    _submit(job_id)
    second_delivery = []

    def compute_while_delivered_again(job_id, work_dir):
        """Receive the same job again while this run computes."""
        second_delivery.append(job_run.run(job_id, _failing_compute))

    try:
        status = job_run.run(job_id, compute_while_delivered_again)

        assert (status, second_delivery) == ("COMPLETED", [None])
        assert load_row(job_id)["status"] == "COMPLETED"
    finally:
        _cleanup(job_id)


def test_a_won_claim_gives_the_row_a_heartbeat():
    """From its first write on, a run is told apart from a queued one."""
    job_id = "test_job_run_claim_beats"
    _submit(job_id)
    heartbeat_during_run = []

    def compute(job_id, work_dir):
        heartbeat_during_run.append(load_row(job_id)["heartbeat_at"])

    try:
        job_run.run(job_id, compute)

        assert heartbeat_during_run[0] is not None
    finally:
        _cleanup(job_id)


def test_a_redelivery_of_a_run_with_a_heartbeat_changes_nothing(caplog):
    """A message redelivered after its worker died does not restart the run."""
    job_id = "test_job_run_redelivered"
    _submit(job_id)
    set_heartbeat(job_id, "11 minutes")
    job_log.append(job_id, "the lost run's last words")
    before = row_and_log(job_id)

    with caplog.at_level(logging.INFO, logger="cosmo_ecosystem.job_run"):
        status = job_run.run(job_id, _failing_compute)

    try:
        assert status is None
        assert row_and_log(job_id) == before
        drops = [r for r in caplog.records if r.name == "cosmo_ecosystem.job_run"]
        assert len(drops) == 1
        assert job_id in drops[0].getMessage()
        assert _job_log_handlers() == []
    finally:
        _cleanup(job_id)


@pytest.mark.parametrize("status", ["PENDING", "COMPLETED", "FAILED"])
def test_a_delivery_for_a_row_that_is_not_running_changes_nothing(status):
    """A stale message after a reset, or one for a cancelled job, is dropped."""
    job_id = "test_job_run_not_running"
    _submit(job_id)
    job_persistence.update_columns(job_id, {"status": status})
    job_log.append(job_id, "cancelled by user")
    before = row_and_log(job_id)

    try:
        assert job_run.run(job_id, _failing_compute) is None
        assert row_and_log(job_id) == before
    finally:
        _cleanup(job_id)


def _wait_for_a_newer_heartbeat(job_id, than, timeout=10):
    """Return the job's heartbeat once it is newer than ``than``, else None."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        heartbeat = load_row(job_id)["heartbeat_at"]
        if heartbeat > than:
            return heartbeat
        time.sleep(0.05)
    return None


def test_the_heartbeat_advances_while_the_computation_runs():
    """A long computation is never mistaken for a lost one."""
    job_id = "test_job_run_heartbeat"
    _submit(job_id)
    advanced = []

    def compute(job_id, work_dir):
        claimed_at = load_row(job_id)["heartbeat_at"]
        advanced.append(_wait_for_a_newer_heartbeat(job_id, claimed_at) is not None)

    try:
        job_run.run(job_id, compute, heartbeat_interval=0.2)

        assert advanced == [True]
    finally:
        _cleanup(job_id)


def test_the_heartbeat_stops_with_the_run():
    """A finished run leaves no thread behind that keeps the row looking alive."""
    job_id = "test_job_run_heartbeat_stops"
    _submit(job_id)

    try:
        job_run.run(job_id, lambda job_id, work_dir: None, heartbeat_interval=0.2)
        last = load_row(job_id)["heartbeat_at"]

        assert _wait_for_a_newer_heartbeat(job_id, last, timeout=1) is None
    finally:
        _cleanup(job_id)


def test_a_failed_heartbeat_is_logged_and_retried(monkeypatch, caplog):
    """A database hiccup costs one beat, not the run's sign of life."""
    job_id = "test_job_run_heartbeat_outage"
    _submit(job_id)
    unreachable = create_engine("postgresql+psycopg2://nobody:none@127.0.0.1:1/none")
    advanced = []

    def compute_through_an_outage(job_id, work_dir):
        """Keep the database away until a beat failed, then wait for the next one."""
        claimed_at = load_row(job_id)["heartbeat_at"]
        monkeypatch.setattr(DbManager, "_Session", sessionmaker(bind=unreachable))
        deadline = time.monotonic() + 10
        while not _heartbeat_failed(caplog) and time.monotonic() < deadline:
            time.sleep(0.05)
        monkeypatch.undo()
        advanced.append(_wait_for_a_newer_heartbeat(job_id, claimed_at) is not None)

    try:
        status = job_run.run(job_id, compute_through_an_outage, heartbeat_interval=0.2)

        assert _heartbeat_failed(caplog)
        assert (status, advanced) == ("COMPLETED", [True])
        # Worker log only: the job log is the database that just failed.
        assert "failed and is retried" not in job_log.read(job_id)
    finally:
        monkeypatch.undo()
        _cleanup(job_id)


def _heartbeat_failed(caplog):
    """Return whether the run reported a failed heartbeat write."""
    return any(
        record.name.startswith("cosmo_ecosystem.job_run")
        and record.levelname == "WARNING"
        and "heartbeat" in record.getMessage()
        for record in caplog.records
    )


def test_a_live_runs_heartbeat_never_claims_a_requeued_row():
    """A run swept by mistake and then resubmitted is not kept alive by the old run.

    The old run's heartbeat thread goes on beating; the re-queued row must still
    have no heartbeat afterwards, so the new delivery wins its claim. The old
    run is overtaken: it writes no final status over the new run's.
    """
    job_id = "test_job_run_requeued_under_a_live_run"
    _submit(job_id)
    seen = []

    def compute_while_swept_and_resubmitted(job_id, work_dir):
        """Sweep the row under this live run, queue it again, let it beat."""
        set_heartbeat(job_id, "11 minutes")
        sweep_lost_runs()
        job_run.mark_queued(job_id)
        time.sleep(1)  # five heartbeat intervals
        seen.append(load_row(job_id)["heartbeat_at"])
        seen.append(job_run.run(job_id, lambda job_id, work_dir: None))

    try:
        overtaken = job_run.run(
            job_id, compute_while_swept_and_resubmitted, heartbeat_interval=0.2
        )

        assert seen == [None, "COMPLETED"]
        assert overtaken is None
        assert load_row(job_id)["status"] == "COMPLETED"
    finally:
        _cleanup(job_id)


def _claim_fails(job_id):
    """A claim that hits a database error after it was sent."""
    raise OperationalError("UPDATE jobs", {}, Exception("hiccup"))


def test_a_claim_that_fails_on_a_still_queued_row_ends_the_run_failed(monkeypatch):
    """A database hiccup at the claim does not leave a job queued forever."""
    job_id = "test_job_run_claim_fails_queued"
    _submit(job_id)
    monkeypatch.setattr(DbManager, "claim_run", _claim_fails)

    try:
        status = job_run.run(job_id, _failing_compute)

        assert status == "FAILED"
        assert load_row(job_id)["status"] == "FAILED"
    finally:
        monkeypatch.undo()
        _cleanup(job_id)


def test_a_claim_that_fails_leaves_a_row_another_delivery_claimed_alone(monkeypatch):
    """A failed claim never fails a run that another delivery is computing."""
    job_id = "test_job_run_claim_fails_claimed"
    _submit(job_id)
    set_heartbeat(job_id)
    before = row_and_log(job_id)
    monkeypatch.setattr(DbManager, "claim_run", _claim_fails)

    try:
        status = job_run.run(job_id, _failing_compute)

        assert status is None
        assert row_and_log(job_id) == before
    finally:
        monkeypatch.undo()
        _cleanup(job_id)


def test_mark_pending_returns_the_row_to_pending_with_no_heartbeat():
    """A reset job carries no trace of its last run's sign of life."""
    job_id = "test_job_run_mark_pending"
    _submit(job_id)
    job_persistence.update_columns(job_id, {"status": "FAILED"})
    set_heartbeat(job_id, "11 minutes")

    try:
        job_run.mark_pending(job_id)

        row = load_row(job_id)
        assert (row["status"], row["heartbeat_at"]) == ("PENDING", None)
    finally:
        _cleanup(job_id)


@pytest.mark.parametrize("mark", [job_run.mark_queued, job_run.mark_pending])
def test_marking_a_job_without_a_row_raises_job_not_found(mark):
    """Queueing or resetting a deleted job fails loud instead of writing nothing."""
    with pytest.raises(JobNotFound):
        mark("test_job_run_mark_no_row")
