"""Test the framework's job persistence against real Postgres and S3 servers."""

import datetime
import os
import shutil
import warnings

import pytest

from cosmo_ecosystem import job_retention, object_storage_manager
from cosmo_ecosystem.config import (
    JOB_WORK_DIR_TEMPLATE,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_REMOTE_NAME,
)
from cosmo_ecosystem.db_manager import DbManager
from cosmo_ecosystem.error_handling import JobNotFound
from cosmo_ecosystem.job_retention import clean_up_jobs
from cosmo_ecosystem.job_persistence import (
    delete_files,
    delete_job,
    delete_jobs,
    load_row,
    save,
    update_columns,
    work_dir,
)
from cosmo_ecosystem.object_storage_manager import (
    ObjectStorageError,
    delete_directory_from_storage,
    get_remote_files,
    save_files,
)

FILE_NAME = "result.csv"
STALE = "stale\n"
FRESH = "fresh\n"


@pytest.fixture
def rclone_calls(monkeypatch):
    """Count the rclone commands object_storage_manager runs."""
    calls = []
    real = object_storage_manager.run_rclone_with_retry

    def counting(params, *args, **kwargs):
        calls.append(params)
        return real(params, *args, **kwargs)

    monkeypatch.setattr(object_storage_manager, "run_rclone_with_retry", counting)
    return calls


def _dir(job_id):
    """Return the local work directory of job_id."""
    return JOB_WORK_DIR_TEMPLATE.format(job_id=job_id)


def _row(job_id, **overrides):
    """Return a complete row for job_id."""
    row = {
        "job_id": job_id,
        "start_date": datetime.date.today(),
        "input_data": {},
        "submitted": False,
        "notified_end": False,
        "logs": "",
        "status": "PENDING",
        "version": "0.1.0",
    }
    return {**row, **overrides}


def _write(job_id, name, content):
    """Write a file into job_id's local work dir."""
    path = os.path.join(_dir(job_id), name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="UTF-8") as f_handle:
        f_handle.write(content)


def _read(job_id, name):
    """Return the content of a file in job_id's local work dir."""
    with open(os.path.join(_dir(job_id), name), encoding="UTF-8") as f_handle:
        return f_handle.read()


def _seed_remote(job_id, name, content):
    """Put a file under job_id's remote prefix only."""
    _write(job_id, name, content)
    save_files(job_id)
    shutil.rmtree(_dir(job_id))


def _remote_files(job_id):
    """List the objects stored below job_id's remote prefix."""
    return get_remote_files(
        f"{OBJECT_STORAGE_REMOTE_NAME}:{OBJECT_STORAGE_BUCKET}/{job_id}"
    )


def _cleanup(job_id):
    """Remove whatever a test left behind for job_id."""
    delete_directory_from_storage(job_id)
    shutil.rmtree(_dir(job_id), ignore_errors=True)
    if DbManager.check_existence(job_id):
        DbManager.delete_job(job_id)


def test_loading_a_row_makes_no_rclone_call(rclone_calls):
    """A status poll costs one database read and nothing in storage."""
    job_id = "test_persistence_load_row"
    DbManager.add_entry(_row(job_id, status="RUNNING"))

    try:
        row = load_row(job_id)

        assert row["status"] == "RUNNING"
        assert rclone_calls == []
    finally:
        _cleanup(job_id)


def test_updating_columns_changes_only_those_columns_and_makes_no_rclone_call(
    rclone_calls,
):
    """A status change costs one database write and nothing in storage."""
    job_id = "test_persistence_update_columns"
    DbManager.add_entry(_row(job_id, version="9.9.9"))

    try:
        update_columns(job_id, {"status": "RUNNING", "submitted": True})

        row = load_row(job_id)
        assert row["status"] == "RUNNING"
        assert row["submitted"] is True
        assert row["version"] == "9.9.9"
        assert rclone_calls == []
    finally:
        _cleanup(job_id)


def test_updating_columns_of_a_missing_row_raises():
    """No row is created by an update: a job that does not exist stays absent."""
    job_id = "test_persistence_update_missing"

    with pytest.raises(JobNotFound):
        update_columns(job_id, {"status": "RUNNING"})

    assert not DbManager.check_existence(job_id)


def test_work_dir_replaces_a_stale_local_file_with_the_remote_version():
    """The remote prefix wins: a changed file is pulled over the local copy."""
    job_id = "test_persistence_work_dir_stale"
    _seed_remote(job_id, FILE_NAME, FRESH)
    _write(job_id, FILE_NAME, STALE)

    try:
        path = work_dir(job_id)

        assert path == _dir(job_id)
        assert _read(job_id, FILE_NAME) == FRESH
    finally:
        _cleanup(job_id)


def test_work_dir_keeps_a_local_file_the_remote_lacks():
    """A pull never deletes: a running worker's outputs may not be uploaded yet."""
    job_id = "test_persistence_work_dir_extra"
    _seed_remote(job_id, FILE_NAME, FRESH)
    _write(job_id, "worker_output.csv", FRESH)

    try:
        work_dir(job_id)

        assert _read(job_id, FILE_NAME) == FRESH
        assert _read(job_id, "worker_output.csv") == FRESH
    finally:
        _cleanup(job_id)


def test_work_dir_of_a_job_with_nothing_uploaded_yet_is_an_empty_dir():
    """A new job has no remote prefix; asking for its dir must still work."""
    job_id = "test_persistence_work_dir_new"

    try:
        path = work_dir(job_id)

        assert os.path.isdir(path)
        assert os.listdir(path) == []
    finally:
        _cleanup(job_id)


def test_saving_uploads_the_work_dir_and_writes_the_row():
    """Both halves of a save land: the files in storage, the row in the database."""
    job_id = "test_persistence_save"
    _write(job_id, FILE_NAME, FRESH)

    try:
        save(job_id, _row(job_id, status="RUNNING"))

        assert _remote_files(job_id) == {FILE_NAME}
        assert load_row(job_id)["status"] == "RUNNING"
        save(job_id, _row(job_id, status="COMPLETED"))
        assert load_row(job_id)["status"] == "COMPLETED"
    finally:
        _cleanup(job_id)


def test_saving_keeps_a_remote_file_the_work_dir_lacks():
    """A web save during a run must not delete the worker's fresh results."""
    job_id = "test_persistence_save_keeps_remote"
    _seed_remote(job_id, "worker_result.csv", FRESH)
    _write(job_id, FILE_NAME, FRESH)

    try:
        save(job_id, _row(job_id))

        assert _remote_files(job_id) == {FILE_NAME, "worker_result.csv"}
    finally:
        _cleanup(job_id)


def test_saving_writes_no_row_when_the_upload_fails(monkeypatch):
    """Files first, row second: a row never points at files not in storage."""
    job_id = "test_persistence_save_upload_fails"
    _write(job_id, FILE_NAME, FRESH)
    # rclone creates a missing bucket on upload, so an unknown remote is what
    # makes the upload fail for real, like an unreachable store.
    monkeypatch.setattr(
        object_storage_manager, "OBJECT_STORAGE_REMOTE_NAME", "no-such-remote"
    )

    try:
        with pytest.raises(ObjectStorageError):
            save(job_id, _row(job_id))

        assert not DbManager.check_existence(job_id)
    finally:
        # Restore the real remote first, so the cleanup reaches the job's prefix.
        monkeypatch.undo()
        _cleanup(job_id)


def test_deleting_a_file_and_a_dir_removes_both_locally_and_remotely():
    """One call clears the work dir and the remote prefix; nothing waits on a sync."""
    job_id = "test_persistence_delete_files"
    _write(job_id, FILE_NAME, FRESH)
    _write(job_id, "keep.csv", FRESH)
    _write(job_id, "plots/a.png", FRESH)
    _write(job_id, "plots/b.png", FRESH)
    save(job_id, _row(job_id))

    try:
        delete_files(job_id, [FILE_NAME, "plots"])

        assert sorted(os.listdir(_dir(job_id))) == ["keep.csv"]
        assert _remote_files(job_id) == {"keep.csv"}
    finally:
        _cleanup(job_id)


def test_deleting_a_file_that_exists_only_remotely_removes_it():
    """The work dir is a cache: a file never pulled here is still deleted."""
    job_id = "test_persistence_delete_files_remote_only"
    _seed_remote(job_id, FILE_NAME, FRESH)
    os.makedirs(_dir(job_id))

    try:
        delete_files(job_id, [FILE_NAME])

        assert _remote_files(job_id) == set()
    finally:
        _cleanup(job_id)


def test_deleting_a_file_that_exists_only_locally_removes_it():
    """A file never uploaded is deleted too."""
    job_id = "test_persistence_delete_files_local_only"
    _seed_remote(job_id, "keep.csv", FRESH)
    _write(job_id, FILE_NAME, FRESH)

    try:
        delete_files(job_id, [FILE_NAME])

        assert os.listdir(_dir(job_id)) == []
        assert _remote_files(job_id) == {"keep.csv"}
    finally:
        _cleanup(job_id)


def test_deleting_a_file_that_is_nowhere_counts_as_deleted():
    """A retry after a partial failure, or a double click, must not raise."""
    job_id = "test_persistence_delete_files_missing"
    _write(job_id, "keep.csv", FRESH)
    save(job_id, _row(job_id))

    try:
        delete_files(job_id, ["gone.csv", "no_dir"])

        assert os.listdir(_dir(job_id)) == ["keep.csv"]
        assert _remote_files(job_id) == {"keep.csv"}
    finally:
        _cleanup(job_id)


def test_deleting_files_of_a_job_without_a_remote_prefix_counts_as_deleted():
    """A job that never uploaded anything has no prefix to delete from."""
    job_id = "test_persistence_delete_files_no_prefix"
    _write(job_id, FILE_NAME, FRESH)

    try:
        delete_files(job_id, [FILE_NAME])

        assert os.listdir(_dir(job_id)) == []
    finally:
        _cleanup(job_id)


def test_delete_job_removes_prefix_dir_and_row_from_its_new_location():
    """Deleting a job clears everything it owns."""
    job_id = "test_persistence_delete_job"
    _write(job_id, FILE_NAME, FRESH)
    save(job_id, _row(job_id))

    delete_job(job_id)

    assert _remote_files(job_id) == set()
    assert not os.path.exists(_dir(job_id))
    assert not DbManager.check_existence(job_id)


def test_importing_delete_job_from_job_retention_warns():
    """The old import path keeps working for one version, loudly."""
    with pytest.warns(DeprecationWarning, match="job_persistence"):
        old_delete_job = job_retention.delete_job
    with pytest.warns(DeprecationWarning, match="job_persistence"):
        old_delete_jobs = job_retention.delete_jobs

    assert old_delete_job is delete_job
    assert old_delete_jobs is delete_jobs


def test_cleaning_up_jobs_does_not_warn():
    """The framework's own cleanup uses the new location silently."""
    job_id = "test_persistence_cleanup_silent"
    DbManager.add_entry(_row(job_id, start_date=datetime.date(2000, 1, 1)))

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            clean_up_jobs()

        assert not DbManager.check_existence(job_id)
    finally:
        _cleanup(job_id)
