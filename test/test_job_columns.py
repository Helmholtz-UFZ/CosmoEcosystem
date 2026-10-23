"""The framework Job fails loud when the app's job table lacks its extra column.

``JobColumns`` leaves ``input_data`` out on purpose (COSMONAUT has no such
column), but the framework ``Job`` reads and writes it. Nothing used to tell an
app that, so the first query failed at runtime instead of at startup.

``logs`` was required too until the job log moved into the ``job_logs`` table;
a job table without it is now complete.
"""

import datetime
import json

import pytest
from sqlalchemy import JSON, Column, String
from sqlalchemy.orm import declarative_base

from cosmo_ecosystem import job_persistence
from cosmo_ecosystem.db_manager import DbManager, JobColumns
from cosmo_ecosystem.job import Job
from cosmo_ecosystem.pydantic_models import UploadJobConfig

JOB_ID = "quiet_amber_otter"


def _table(*extra_columns):
    """Declare a job table carrying JobColumns plus the given extra columns."""
    attributes = {"__tablename__": "jobs", **dict(extra_columns)}
    return type("JobTable", (JobColumns, declarative_base()), attributes)


@pytest.fixture
def configured_job_class(monkeypatch):
    """Point Job at a config model so only the column check can raise."""
    monkeypatch.setattr(Job, "config_model", UploadJobConfig)


def test_construction_raises_naming_the_missing_input_data_column(
    configured_job_class, monkeypatch
):
    """A job table without input_data is rejected, naming the column."""
    monkeypatch.setattr(DbManager, "job_table", _table(("logs", Column(String))))

    with pytest.raises(RuntimeError, match="input_data"):
        Job(job_id=JOB_ID)


def test_a_job_table_without_a_logs_column_loads_a_job(
    configured_job_class, monkeypatch
):
    """The job log lives in job_logs, so the job table needs no logs column."""
    monkeypatch.setattr(DbManager, "job_table", _table(("input_data", Column(JSON))))
    # The row as the database would return it; the suite has no database.
    row = {
        "job_id": JOB_ID,
        "start_date": datetime.date.today(),
        "input_data": json.dumps({"job_id": JOB_ID}),
        "submitted": False,
        "notified_end": False,
        "status": "PENDING",
        "version": "0.1.0",
    }
    monkeypatch.setattr(job_persistence, "load_row", lambda job_id: row)

    job = Job(job_id=JOB_ID)

    assert job.status == "PENDING"
