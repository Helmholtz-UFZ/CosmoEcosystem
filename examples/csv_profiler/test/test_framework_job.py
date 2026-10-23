"""Test the framework Job's job log and submit against real Postgres and S3."""

import logging
import os

import pytest

from cosmo_ecosystem import job_log
from cosmo_ecosystem.constants import LOG_FILE_NAME
from cosmo_ecosystem.job import Job
from cosmo_ecosystem.job_log import JobLogHandler
from cosmo_ecosystem.job_persistence import delete_job, load_row, local_dir

from csv_profiler.pydantic_models import ProfileConfig


@pytest.fixture
def framework_job(monkeypatch):
    """Wire the framework Job to the CSV domain, as app.py does at startup."""
    monkeypatch.setattr(Job, "config_model", ProfileConfig)
    monkeypatch.setattr(Job, "file_validator", None)


@pytest.fixture
def new_job(framework_job, request):
    """Create a fresh job named after the test; delete it afterwards."""
    # Job ids are at most 50 characters long.
    job_id = f"test_fw_job_{request.node.name.removeprefix('test_')}"[:50]
    job = Job(new_job_id=job_id)
    yield job
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
