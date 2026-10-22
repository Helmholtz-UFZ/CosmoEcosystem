"""The framework Job fails loud when the app's job table lacks its extra columns.

``JobColumns`` leaves ``input_data`` and ``logs`` out on purpose (COSMONAUT has
neither), but the framework ``Job`` reads and writes both. Nothing used to tell
an app that, so the first query failed at runtime instead of at startup.
"""

import pytest
from sqlalchemy import JSON, Column, String
from sqlalchemy.orm import declarative_base

from cosmo_ecosystem.db_manager import DbManager, JobColumns
from cosmo_ecosystem.job import Job
from cosmo_ecosystem.pydantic_models import UploadJobConfig


def _table(*extra_columns):
    """Declare a job table carrying JobColumns plus the given extra columns."""
    attributes = {"__tablename__": "jobs", **dict(extra_columns)}
    return type("JobTable", (JobColumns, declarative_base()), attributes)


@pytest.fixture
def configured_job_class(monkeypatch):
    """Point Job at a config model so only the column check can raise."""
    monkeypatch.setattr(Job, "config_model", UploadJobConfig)


@pytest.mark.parametrize(
    ("present", "missing"),
    [
        ((("logs", Column(String)),), "input_data"),
        ((("input_data", Column(JSON)),), "logs"),
    ],
)
def test_construction_raises_naming_the_missing_column(
    configured_job_class, monkeypatch, present, missing
):
    """A job table without input_data or logs is rejected, naming the column."""
    monkeypatch.setattr(DbManager, "job_table", _table(*present))

    with pytest.raises(RuntimeError, match=missing):
        Job(job_id="quiet_amber_otter")
