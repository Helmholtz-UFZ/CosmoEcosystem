"""Test the framework Job's job log and submit against real Postgres and S3."""

import base64
import datetime
import json
import logging
import os
import re

import pytest

from cosmo_ecosystem import job_log, job_persistence, job_run
from cosmo_ecosystem.constants import LOG_FILE_NAME
from cosmo_ecosystem.config import OBJECT_STORAGE_BUCKET, OBJECT_STORAGE_REMOTE_NAME
from cosmo_ecosystem.db_manager import DbManager
from cosmo_ecosystem.error_handling import FileValidationError
from cosmo_ecosystem.job import Job
from cosmo_ecosystem.job_log import JobLogHandler
from cosmo_ecosystem.job_persistence import delete_job, load_row, local_dir
from cosmo_ecosystem.job_persistence import update_columns
from cosmo_ecosystem.object_storage_manager import ObjectStorageError, get_remote_files

from csv_profiler.pydantic_models import ProfileConfig
from job_row_helpers import drop_row, set_heartbeat, set_row_columns


@pytest.fixture
def framework_job(monkeypatch):
    """Wire the framework Job to the CSV domain, as app.py does at startup."""
    monkeypatch.setattr(Job, "config_model", ProfileConfig)
    monkeypatch.setattr(Job, "file_validator", None)


@pytest.fixture
def new_job(framework_job, request):
    """Create a fresh job named after the test; delete it afterwards."""
    # Job ids are at most 50 characters long.
    name = re.sub(r"\W", "_", request.node.name.removeprefix("test_"))
    job_id = f"test_fw_job_{name}"[:50]
    job = Job(new_job_id=job_id)
    yield job
    drop_row(job_id)
    delete_job(job_id)


def _log_as_the_worker(job_id, message):
    """Write message to job_id's job log the way a worker's job run does."""
    logger = logging.getLogger(f"test_framework_job.{job_id}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    handler = JobLogHandler(job_id)
    logger.addHandler(handler)
    logger.info(message)
    logger.removeHandler(handler)
    handler.close()


def test_reload_logs_shows_the_job_log_without_a_log_file_in_the_work_dir(new_job):
    """The status poll shows a running job's log, whichever pod serves the page."""
    _log_as_the_worker(new_job.job_id, "profiled column age")

    job = Job(job_id=new_job.job_id)
    job.reload_logs()

    assert "profiled column age" in job.logs
    assert not os.path.exists(os.path.join(local_dir(job.job_id), LOG_FILE_NAME))


def test_reset_leaves_an_empty_job_log(new_job):
    """After a reset, the old run's output cannot be mistaken for a new one's."""
    _log_as_the_worker(new_job.job_id, "an earlier run")

    new_job.reset()

    assert job_log.read(new_job.job_id) == ""


def test_a_submit_handler_that_fails_leaves_the_job_failed(new_job, monkeypatch):
    """RUNNING goes in before the enqueue, so a fast worker's status is never lost.

    A handler that reports failure turns the job FAILED.
    """
    status_seen_by_handler = []

    def failing_handler(job):
        status_seen_by_handler.append(load_row(job.job_id)["status"])
        return None, True

    monkeypatch.setattr(Job, "submit_handler", staticmethod(failing_handler))

    new_job.submit()

    assert status_seen_by_handler == ["RUNNING"]
    assert load_row(new_job.job_id)["status"] == "FAILED"


class _BrokerDown(Exception):
    """Raised by a submit handler that cannot reach the broker."""


def test_a_submit_handler_that_raises_leaves_the_job_failed_and_says_why(
    new_job, monkeypatch
):
    """A broken enqueue does not leave the job RUNNING with no worker behind it.

    The error still reaches the caller, so the global error handler shows it.
    """

    def raising_handler(job):
        raise _BrokerDown("redis unreachable")

    monkeypatch.setattr(Job, "submit_handler", staticmethod(raising_handler))

    with pytest.raises(_BrokerDown):
        new_job.submit()

    assert load_row(new_job.job_id)["status"] == "FAILED"
    assert f"Cannot start job {new_job.job_id}" in job_log.read(new_job.job_id)


def test_submit_queues_the_run_with_no_heartbeat(new_job, monkeypatch):
    """A resubmitted job's old heartbeat is gone before the worker sees the message."""
    set_heartbeat(new_job.job_id)
    row_seen_by_handler = []

    def handler(job):
        row = load_row(job.job_id)
        row_seen_by_handler.append((row["status"], row["heartbeat_at"]))
        return "task-id", False

    monkeypatch.setattr(Job, "submit_handler", staticmethod(handler))

    new_job.submit()

    assert row_seen_by_handler == [("RUNNING", None)]
    assert new_job.status == "RUNNING"


def test_reset_clears_the_heartbeat(new_job):
    """A reset job is PENDING with no trace of its last run's sign of life."""
    set_heartbeat(new_job.job_id)

    new_job.reset()

    row = load_row(new_job.job_id)
    assert (row["status"], row["heartbeat_at"]) == ("PENDING", None)


def test_saving_a_job_keeps_its_runs_heartbeat(new_job):
    """A page that saves the job during a run does not write the heartbeat back."""
    job = Job(job_id=new_job.job_id)
    set_heartbeat(new_job.job_id)
    beat = load_row(new_job.job_id)["heartbeat_at"]

    job.save()

    assert load_row(new_job.job_id)["heartbeat_at"] == beat


def test_a_job_loaded_before_a_run_ended_does_not_save_its_old_state_back(new_job):
    """A stale tab saving its job leaves what the run and the sweep wrote."""
    job_run.mark_queued(new_job.job_id)
    job = Job(job_id=new_job.job_id)  # loaded while RUNNING, submitted
    set_heartbeat(new_job.job_id, "11 minutes")
    set_row_columns(new_job.job_id, status="FAILED", submitted=False)
    swept = load_row(new_job.job_id)

    job.save()

    assert load_row(new_job.job_id) == swept


def test_a_job_loaded_as_pending_does_not_save_pending_over_a_running_job(new_job):
    """The input page's old copy of the job cannot reset a job that started."""
    job = Job(job_id=new_job.job_id)  # loaded while PENDING
    job_run.mark_queued(new_job.job_id)
    queued = load_row(new_job.job_id)

    job.save()

    assert load_row(new_job.job_id) == queued


def test_a_new_job_is_inserted_pending_and_not_submitted(new_job):
    """The one place the framework writes a status is the creation of the row."""
    row = load_row(new_job.job_id)

    assert (row["status"], row["submitted"]) == ("PENDING", False)
    assert (row["heartbeat_at"], row["run_id"]) == (None, None)


@pytest.mark.parametrize("column", ["status", "submitted", "heartbeat_at", "run_id"])
def test_save_attributes_refuses_the_columns_a_run_owns(new_job, column):
    """An attribute save cannot become a back door for a status write."""
    with pytest.raises(ValueError, match=column):
        new_job.save_attributes([column])


@pytest.fixture
def counted_handler(monkeypatch):
    """Wire a submit handler that records its calls and enqueues successfully."""
    calls = []

    def handler(job):
        calls.append(job.job_id)
        return "task-id", False

    monkeypatch.setattr(Job, "submit_handler", staticmethod(handler))
    return calls


def test_submitting_twice_enqueues_one_run(new_job, counted_handler):
    """Two clicks, or two tabs, start exactly one job run."""
    first = new_job.submit()
    second = Job(job_id=new_job.job_id).submit()

    assert (first, second) == (True, False)
    assert counted_handler == [new_job.job_id]
    row = load_row(new_job.job_id)
    assert (row["status"], row["submitted"]) == ("RUNNING", True)


@pytest.mark.parametrize("status", ["RUNNING", "COMPLETED"])
def test_lost_guard_does_nothing(new_job, counted_handler, status):
    """A submit that loses the guard saves nothing, pulls nothing, enqueues nothing."""
    set_row_columns(new_job.job_id, status=status)
    job = Job(job_id=new_job.job_id)
    job.model.upload_file_name = "an_unsaved_change.csv"
    before = load_row(new_job.job_id)

    assert job.submit() is False

    assert load_row(new_job.job_id) == before
    assert counted_handler == []


def test_a_failed_job_is_submitted_again_directly(new_job, counted_handler):
    """Resubmitting a FAILED job needs no reset."""
    set_row_columns(new_job.job_id, status="FAILED")

    assert Job(job_id=new_job.job_id).submit() is True

    assert load_row(new_job.job_id)["status"] == "RUNNING"


def test_a_handler_that_fails_after_a_worker_claimed_the_run_leaves_the_row(
    new_job, monkeypatch
):
    """FAILED is written only while the run is still queued, never over a live run."""

    def claiming_then_raising_handler(job):
        assert DbManager.claim_run(job.job_id)
        raise _BrokerDown("redis unreachable after the message was delivered")

    monkeypatch.setattr(
        Job, "submit_handler", staticmethod(claiming_then_raising_handler)
    )

    with pytest.raises(_BrokerDown):
        new_job.submit()

    row = load_row(new_job.job_id)
    assert row["status"] == "RUNNING"
    assert row["heartbeat_at"] is not None


def test_reset_returns_true_and_clears_the_results(new_job):
    """A reset reports that it happened."""
    assert new_job.reset() is True


def test_reset_is_refused_while_the_job_runs(new_job):
    """A reset deletes nothing and writes nothing under a live run."""
    with open(os.path.join(new_job.working_dir, "result.json"), "w") as f:
        f.write("{}")
    new_job.save()
    job_run.mark_queued(new_job.job_id)
    _log_as_the_worker(new_job.job_id, "a live run")
    before = load_row(new_job.job_id)
    job = Job(job_id=new_job.job_id)

    assert job.reset() is False

    assert load_row(new_job.job_id) == before
    assert "a live run" in job_log.read(new_job.job_id)
    assert os.path.exists(os.path.join(local_dir(new_job.job_id), "result.json"))


def _remote_names(job_id):
    """List the names of the objects in job_id's remote prefix."""
    return set(
        get_remote_files(
            f"{OBJECT_STORAGE_REMOTE_NAME}:{OBJECT_STORAGE_BUCKET}/{job_id}"
        )
    )


def _a_changed_input(job):
    """Change the in-memory input of job and return its JSON, as save_input writes it."""
    job.model.upload_file_name = "changed.csv"
    with open(os.path.join(job.working_dir, "changed.csv"), "w") as f:
        f.write("a,b\n1,2\n")
    return job._get_column_data("input_data")


def test_saving_the_input_of_a_pending_job_writes_only_the_input(new_job):
    """The input write leaves start date, submitted mark and status as they are."""
    update_columns(new_job.job_id, {"start_date": datetime.date(2020, 1, 1)})
    job = Job(job_id=new_job.job_id)
    job.start_date = datetime.date.today()  # a stale or new copy must not be written
    changed = _a_changed_input(job)

    assert job.save_input() is True

    row = load_row(new_job.job_id)
    assert json.loads(row["input_data"]) == json.loads(changed)
    assert row["start_date"] == datetime.date(2020, 1, 1)
    assert (row["status"], row["submitted"]) == ("PENDING", False)
    assert "changed.csv" in _remote_names(new_job.job_id)


@pytest.mark.parametrize("status", ["RUNNING", "COMPLETED", "FAILED"])
def test_input_of_a_started_job_is_kept(new_job, status):
    """A page loaded while PENDING cannot rewrite the input of a started job."""
    job = Job(job_id=new_job.job_id)
    set_row_columns(new_job.job_id, status=status)
    _a_changed_input(job)
    before = load_row(new_job.job_id)

    assert job.save_input() is False

    assert load_row(new_job.job_id) == before
    assert "changed.csv" not in _remote_names(new_job.job_id)


def test_uploading_a_file_to_a_running_job_is_refused_and_keeps_its_files(new_job):
    """An upload cannot delete or replace the files a run is using."""
    job_run.mark_queued(new_job.job_id)
    job = Job(job_id=new_job.job_id)
    before = load_row(new_job.job_id)

    with pytest.raises(FileValidationError, match="PENDING"):
        job.upload_file("data:text/csv;base64", base64.b64encode(b"a\n1\n"), "new.csv")

    assert load_row(new_job.job_id) == before
    assert "new.csv" not in _remote_names(new_job.job_id)


def test_a_save_that_fails_after_the_guard_leaves_the_job_failed(
    new_job, counted_handler, monkeypatch
):
    """A storage error between the guard and the enqueue does not strand a queued run."""

    def save_fails(job_id, row):
        raise ObjectStorageError("the bucket is unreachable")

    monkeypatch.setattr(job_persistence, "save", save_fails)

    with pytest.raises(ObjectStorageError):
        new_job.submit()

    assert load_row(new_job.job_id)["status"] == "FAILED"
    assert counted_handler == []
    assert f"Cannot start job {new_job.job_id}" in job_log.read(new_job.job_id)


def test_a_work_dir_pull_that_fails_after_the_guard_leaves_the_job_failed(
    new_job, counted_handler, monkeypatch
):
    """The same for the pull: every step after the guard is under the failure path."""

    def pull_fails(job_id):
        raise ObjectStorageError("the bucket is unreachable")

    monkeypatch.setattr(job_persistence, "work_dir", pull_fails)

    with pytest.raises(ObjectStorageError):
        new_job.submit()

    assert load_row(new_job.job_id)["status"] == "FAILED"


def test_delete_returns_false_for_a_running_job_and_true_otherwise(new_job):
    """Job.delete passes the refusal on, so the page can show its hint."""
    job_run.mark_queued(new_job.job_id)
    assert Job(job_id=new_job.job_id).delete() is False
    assert DbManager.check_existence(new_job.job_id)

    set_row_columns(new_job.job_id, status="FAILED")

    assert Job(job_id=new_job.job_id).delete() is True
    assert not DbManager.check_existence(new_job.job_id)
