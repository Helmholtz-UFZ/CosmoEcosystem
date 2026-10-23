"""Test the db_manager class."""

import datetime

from cosmo_ecosystem.db_manager import DbManager


def test_add_and_check_existence():
    """Test adding a job entry and checking its existence."""
    job_id = "test_job_db_manager"

    data_to_insert = {
        "job_id": job_id,
        "start_date": datetime.date(2024, 3, 12),
        "input_data": {"param1": 10, "param2": "value"},
        "submitted": True,
        "notified_end": False,
        "status": "completed",
        "version": "1.0.0",
    }
    DbManager.add_entry(data_to_insert)
    assert DbManager.check_existence(job_id)


def test_get_job_columns():
    """Test retrieving job columns."""
    job_id = "test_job_columns"

    data_to_insert = {
        "job_id": job_id,
        "start_date": datetime.date(2024, 6, 1),
        "input_data": {"key": "val"},
        "submitted": False,
        "notified_end": False,
        "status": "PENDING",
        "version": "0.1.0",
    }
    DbManager.add_entry(data_to_insert)
    columns = DbManager.get_job_columns(job_id)
    assert columns["job_id"] == job_id
    assert columns["status"] == "PENDING"


def test_update_column():
    """Test updating specific columns."""
    job_id = "test_job_update"

    data_to_insert = {
        "job_id": job_id,
        "start_date": datetime.date(2024, 6, 1),
        "input_data": {},
        "submitted": False,
        "notified_end": False,
        "status": "PENDING",
        "version": "0.1.0",
    }
    DbManager.add_entry(data_to_insert)
    DbManager.update_column(job_id, {"status": "COMPLETED"})
    columns = DbManager.get_job_columns(job_id)
    assert columns["status"] == "COMPLETED"


def test_delete_job():
    """Test deleting a job."""
    job_id = "test_job_delete"

    data_to_insert = {
        "job_id": job_id,
        "start_date": datetime.date(2024, 6, 1),
        "input_data": {},
        "submitted": False,
        "notified_end": False,
        "status": "PENDING",
        "version": "0.1.0",
    }
    DbManager.add_entry(data_to_insert)
    assert DbManager.check_existence(job_id)
    DbManager.delete_job(job_id)
    assert not DbManager.check_existence(job_id)


def test_list_jobs():
    """Test listing all jobs."""
    job_id = "test_job_list_"

    for i in range(3):
        data_to_insert = {
            "job_id": f"{job_id}{i}",
            "start_date": datetime.date(2024, 6, 1),
            "input_data": {},
            "submitted": False,
            "notified_end": False,
            "status": "PENDING",
            "version": "0.1.0",
        }
        DbManager.add_entry(data_to_insert)

    jobs = DbManager.list_jobs()
    found = [jid for jid in jobs if jid.startswith(job_id)]
    assert len(found) == 3
