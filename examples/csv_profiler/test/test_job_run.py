"""Test the framework's job run against real Postgres and S3 servers."""

import datetime
import logging
import os
import shutil
import time

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cosmo_ecosystem import job_log, job_run, object_storage_manager
from cosmo_ecosystem.config import OBJECT_STORAGE_BUCKET, OBJECT_STORAGE_REMOTE_NAME
from cosmo_ecosystem.db_manager import DbManager
from cosmo_ecosystem.job_log import JobLogHandler
from cosmo_ecosystem.job_persistence import load_row, local_dir
from cosmo_ecosystem.object_storage_manager import (
    delete_directory_from_storage,
    get_remote_files,
    save_files,
)

# Wires the framework Job seams exactly as the worker process has them.
import csv_profiler.celery_app  # noqa: F401
from csv_profiler.pydantic_models import ProfileConfig
from csv_profiler.tasks.computation_tasks import profile

SAMPLE_CSV = os.path.join(os.path.dirname(__file__), "sample_mixed.csv")
CSV_NAME = "sample_mixed.csv"

log = logging.getLogger(__name__)


def _submit(job_id, input_data=None):
    """Create job_id as submitted: its CSV in the remote prefix, its row PENDING."""
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


def test_a_job_without_a_row_ends_failed_and_no_row_appears():
    """A task for a job deleted meanwhile fails quietly instead of resurrecting it."""
    job_id = "test_job_run_no_row"

    try:
        status = job_run.run(job_id, _failing_compute)

        assert status == "FAILED"
        assert not DbManager.check_existence(job_id)
        assert "JobNotFound" in job_log.read(job_id)
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
