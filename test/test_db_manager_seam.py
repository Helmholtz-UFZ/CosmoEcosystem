"""Tests for the ``JobColumns`` / ``DbManager.job_table`` persistence seam.

See docs/plan/slice2b-framework-batch4.md and docs/conventions/database_schema.md.
"""

import pytest

from cosmo_ecosystem.db_manager import Base, DbManager, JobColumns
from cosmo_ecosystem.error_handling import JobTableNotConfigured


def test_framework_registers_no_jobs_table():
    """Sonst kann keine App ihre eigene jobs-Tabelle deklarieren."""
    import cosmo_ecosystem.db_manager  # noqa: F401
    import cosmo_ecosystem.files_route  # noqa: F401
    import cosmo_ecosystem.job  # noqa: F401

    assert "jobs" not in Base.metadata.tables
    assert "logs" in Base.metadata.tables


def test_job_columns_has_exactly_six_columns():
    """The mixin carries only the columns measured across all three consumers."""
    column_names = {
        name
        for name, value in vars(JobColumns).items()
        if not name.startswith("_") and hasattr(value, "type")
    }
    assert column_names == {
        "job_id",
        "start_date",
        "submitted",
        "notified_end",
        "status",
        "version",
    }


def test_job_table_not_configured_raises_named_error():
    """Calling a job method before the app sets ``job_table`` fails loud, not with AttributeError."""
    original = DbManager.job_table
    DbManager.job_table = None
    try:
        with pytest.raises(JobTableNotConfigured):
            DbManager.list_jobs()
    finally:
        DbManager.job_table = original
