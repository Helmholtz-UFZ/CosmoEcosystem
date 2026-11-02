"""Test the framework's sweep of lost job runs against a real Postgres.

"Stale" is set in SQL relative to the database's now(), never with a mocked clock.
"""

import datetime
from datetime import timedelta

import pytest
from cosmo_ecosystem import job_log, job_run
from cosmo_ecosystem.db_manager import DbManager
from cosmo_ecosystem.job_persistence import load_row, update_columns
from cosmo_ecosystem.tasks.sweep_tasks import sweep_lost_runs

# Wires DbManager.job_table exactly as the worker process has it.
import csv_profiler.domain  # noqa: F401
from job_row_helpers import set_heartbeat

LOST_RUN_LINE = "Worker lost: no heartbeat since"


def _queued(job_id):
    """Create job_id with its run queued: RUNNING, no heartbeat."""
    DbManager.add_entry(
        {
            "job_id": job_id,
            "start_date": datetime.date.today(),
            "input_data": "{}",
            "submitted": True,
            "notified_end": False,
            "status": "PENDING",
            "version": "0.1.0",
        }
    )
    job_run.mark_queued(job_id)


@pytest.fixture
def jobs():
    """Create the jobs a test names; delete them and their job logs afterwards."""
    created = []

    def create(job_id):
        _queued(job_id)
        created.append(job_id)
        return job_id

    yield create
    for job_id in created:
        job_log.clear(job_id)
        DbManager.delete_job(job_id)


def test_the_sweep_fails_only_running_rows_whose_heartbeat_stopped(jobs):
    """A dead run ends FAILED; a live, a queued and a finished one are untouched."""
    lost = jobs("test_sweep_lost")
    set_heartbeat(lost, "11 minutes")
    live = jobs("test_sweep_live")
    set_heartbeat(live, "1 minute")
    queued = jobs("test_sweep_queued")
    finished = jobs("test_sweep_finished")
    set_heartbeat(finished, "11 minutes")
    update_columns(finished, {"status": "COMPLETED"})

    swept = sweep_lost_runs()

    assert lost in swept
    assert not {live, queued, finished} & set(swept)
    statuses = {
        job_id: load_row(job_id)["status"] for job_id in (lost, live, queued, finished)
    }
    assert statuses == {
        lost: "FAILED",
        live: "RUNNING",
        queued: "RUNNING",
        finished: "COMPLETED",
    }


def test_a_swept_run_says_why_in_its_job_log(jobs):
    """The user learns that the worker was lost, when, and what to do."""
    lost = jobs("test_sweep_says_why")
    set_heartbeat(lost, "11 minutes")
    heartbeat = load_row(lost)["heartbeat_at"]

    sweep_lost_runs()

    content = job_log.read(lost)
    assert f"ERROR in sweep_tasks: {LOST_RUN_LINE} {heartbeat:%Y-%m-%d %H:%M:%S}" in (
        content
    )
    assert "is not retried. Reset the job to run it again." in content


def test_the_threshold_is_a_parameter(jobs):
    """With no grace at all, any run with a heartbeat counts as lost."""
    recent = jobs("test_sweep_threshold")
    set_heartbeat(recent, "1 second")

    assert recent not in sweep_lost_runs()
    assert recent in sweep_lost_runs(threshold=timedelta(0))
