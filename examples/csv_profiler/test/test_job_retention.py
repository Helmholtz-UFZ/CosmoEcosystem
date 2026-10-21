"""Test the framework's job retention against real Postgres and S3 servers."""

import datetime
import os
import shutil

import pytest

from cosmo_ecosystem.config import (
    JOB_WORK_DIR_TEMPLATE,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_REMOTE_NAME,
)
from cosmo_ecosystem.db_manager import DbManager
from cosmo_ecosystem.job_retention import delete_job
from cosmo_ecosystem import object_storage_manager
from cosmo_ecosystem.object_storage_manager import (
    ObjectStorageError,
    delete_directory_from_storage,
    get_remote_files,
    save_files,
)

FILE_NAME = "result.csv"
CONTENT = "col_a,col_b\n1,2\n"


def _work_dir(job_id):
    """Return the local work directory of job_id."""
    return JOB_WORK_DIR_TEMPLATE.format(job_id=job_id)


def _seed_row(job_id):
    """Insert a database row for job_id."""
    DbManager.add_entry(
        {
            "job_id": job_id,
            "start_date": datetime.date.today(),
            "input_data": {},
            "submitted": False,
            "notified_end": False,
            "logs": "",
            "status": "PENDING",
            "version": "0.1.0",
        }
    )


def _seed_local(job_id):
    """Write a file into job_id's local work directory."""
    os.makedirs(_work_dir(job_id), exist_ok=True)
    with open(
        os.path.join(_work_dir(job_id), FILE_NAME), "w", encoding="UTF-8"
    ) as f_handle:
        f_handle.write(CONTENT)


def _seed_remote(job_id):
    """Upload job_id's local work directory to its remote prefix."""
    _seed_local(job_id)
    save_files(job_id)


def _remote_files(job_id):
    """List the objects stored below job_id's remote prefix."""
    return get_remote_files(
        f"{OBJECT_STORAGE_REMOTE_NAME}:{OBJECT_STORAGE_BUCKET}/{job_id}"
    )


def _cleanup(job_id):
    """Remove whatever a failed test left behind for job_id."""
    delete_directory_from_storage(job_id)
    shutil.rmtree(_work_dir(job_id), ignore_errors=True)
    if DbManager.check_existence(job_id):
        DbManager.delete_job(job_id)


def test_deleting_a_job_removes_its_row_local_directory_and_remote_prefix():
    """A deleted job is gone from the database, the local disk and S3."""
    job_id = "test_retention_delete_live"
    _seed_row(job_id)
    _seed_remote(job_id)
    assert _remote_files(job_id) == {FILE_NAME}

    try:
        delete_job(job_id)

        assert not DbManager.check_existence(job_id)
        assert not os.path.exists(_work_dir(job_id))
        assert _remote_files(job_id) == set()
    finally:
        _cleanup(job_id)


def test_deleting_a_job_this_pod_never_touched_still_removes_it_everywhere():
    """No local work dir on this pod: the remote prefix and the row still go.

    This is the multi-pod case: the job's files exist only in S3 because
    another pod handled it.
    """
    job_id = "test_retention_delete_no_local"
    _seed_row(job_id)
    _seed_remote(job_id)
    shutil.rmtree(_work_dir(job_id))
    assert _remote_files(job_id) == {FILE_NAME}

    try:
        delete_job(job_id)

        assert not DbManager.check_existence(job_id)
        assert not os.path.exists(_work_dir(job_id))
        assert _remote_files(job_id) == set()
    finally:
        _cleanup(job_id)


def test_deleting_a_job_whose_row_is_already_gone_finishes_the_rest():
    """A row deleted by an earlier, interrupted run does not block the files.

    Another pod or the dashboard may have removed the row first; deleting
    again must still clear what is left instead of raising JobNotFound.
    """
    job_id = "test_retention_delete_no_row"
    _seed_remote(job_id)
    assert _remote_files(job_id) == {FILE_NAME}

    try:
        delete_job(job_id)

        assert not os.path.exists(_work_dir(job_id))
        assert _remote_files(job_id) == set()
    finally:
        _cleanup(job_id)


def test_deleting_a_job_that_never_uploaded_anything_succeeds():
    """No remote prefix: the row and the local work dir still go."""
    job_id = "test_retention_delete_no_remote"
    _seed_row(job_id)
    _seed_local(job_id)
    assert _remote_files(job_id) == set()

    try:
        delete_job(job_id)

        assert not DbManager.check_existence(job_id)
        assert not os.path.exists(_work_dir(job_id))
    finally:
        _cleanup(job_id)


def test_a_failed_remote_deletion_keeps_the_row_for_the_next_run(monkeypatch):
    """The row is the retry handle: it must outlive a failed S3 deletion.

    A bucket that does not exist makes rclone fail for real (exit 3), the
    same way an unreachable store does after the retries.
    """
    job_id = "test_retention_delete_remote_fails"
    _seed_row(job_id)
    _seed_local(job_id)
    monkeypatch.setattr(
        object_storage_manager, "OBJECT_STORAGE_BUCKET", "no-such-bucket"
    )

    try:
        with pytest.raises(ObjectStorageError):
            delete_job(job_id)

        assert DbManager.check_existence(job_id)
        assert os.path.exists(_work_dir(job_id))
    finally:
        # Restore the real bucket first, so the cleanup reaches the seeded job.
        monkeypatch.undo()
        _cleanup(job_id)
