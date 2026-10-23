"""Test the framework's job persistence against real Postgres and S3 servers."""

import datetime
import io
import json
import os
import shutil
import warnings
import zipfile

import dash
import pytest

from cosmo_ecosystem import job_retention, object_storage_manager
from cosmo_ecosystem.config import (
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_REMOTE_NAME,
)
from cosmo_ecosystem.db_manager import DbManager
from cosmo_ecosystem.error_handling import JobNotFound
from cosmo_ecosystem.files_route import serve_files
from cosmo_ecosystem.job import Job
from cosmo_ecosystem.job_retention import clean_up_jobs
from cosmo_ecosystem.job_persistence import (
    delete_files,
    delete_job,
    delete_jobs,
    load_row,
    local_dir,
    pull_file,
    save,
    update_columns,
    upload_work_dir,
    work_dir,
)
from cosmo_ecosystem.object_storage_manager import (
    ObjectStorageError,
    delete_directory_from_storage,
    get_remote_files,
    save_files,
)

from csv_profiler.pydantic_models import ProfileConfig

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
    return local_dir(job_id)


def _row(job_id, **overrides):
    """Return a complete row for job_id."""
    row = {
        "job_id": job_id,
        "start_date": datetime.date.today(),
        "input_data": {},
        "submitted": False,
        "notified_end": False,
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


def test_saving_a_job_whose_work_dir_does_not_exist_writes_the_row():
    """A job saved from a pod that never held its files uploads nothing, no error."""
    job_id = "test_persistence_save_no_dir"
    shutil.rmtree(_dir(job_id), ignore_errors=True)

    try:
        save(job_id, _row(job_id, status="RUNNING"))

        assert load_row(job_id)["status"] == "RUNNING"
        assert _remote_files(job_id) == set()
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


def test_uploading_the_work_dir_leaves_the_job_row_untouched():
    """A job run uploads its results without a row; the row stays as it was."""
    job_id = "test_persistence_upload_row_untouched"
    DbManager.add_entry(_row(job_id, status="RUNNING", version="9.9.9"))
    row_before = load_row(job_id)
    _write(job_id, FILE_NAME, FRESH)

    try:
        upload_work_dir(job_id)

        assert _remote_files(job_id) == {FILE_NAME}
        assert load_row(job_id) == row_before
    finally:
        _cleanup(job_id)


def test_uploading_the_work_dir_keeps_a_remote_file_the_work_dir_lacks():
    """Like save, the upload deletes nothing remote (ADR 0001)."""
    job_id = "test_persistence_upload_keeps_remote"
    _seed_remote(job_id, "worker_result.csv", FRESH)
    _write(job_id, FILE_NAME, FRESH)

    try:
        upload_work_dir(job_id)

        assert _remote_files(job_id) == {FILE_NAME, "worker_result.csv"}
    finally:
        _cleanup(job_id)


def test_uploading_the_work_dir_raises_when_the_upload_fails(monkeypatch):
    """A failed upload is loud, so a caller never writes a row after it."""
    job_id = "test_persistence_upload_fails"
    _write(job_id, FILE_NAME, FRESH)
    # An unknown remote, as in the save case: rclone creates a missing bucket.
    monkeypatch.setattr(
        object_storage_manager, "OBJECT_STORAGE_REMOTE_NAME", "no-such-remote"
    )

    try:
        with pytest.raises(ObjectStorageError):
            upload_work_dir(job_id)
    finally:
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


# --- the framework Job and the files route on top of the module -------------


@pytest.fixture
def framework_job(monkeypatch):
    """Wire the framework Job to the CSV domain, as app.py does at startup."""
    monkeypatch.setattr(Job, "config_model", ProfileConfig)
    monkeypatch.setattr(Job, "file_validator", None)


def _job_row(job_id, **overrides):
    """Return a complete row whose input_data the framework Job can parse.

    The framework Job stores input_data as a JSON string, not a JSON object.
    """
    return _row(job_id, input_data=json.dumps({"job_id": job_id}), **overrides)


def test_a_status_poll_of_the_framework_job_makes_no_rclone_call(
    framework_job, rclone_calls
):
    """Loading a Job and refreshing its logs, as the 2 s poll does, stays off rclone."""
    job_id = "test_persistence_job_poll"
    DbManager.add_entry(_job_row(job_id, status="RUNNING"))

    try:
        job = Job(job_id=job_id)
        job.reload_logs()

        assert job.status == "RUNNING"
        assert rclone_calls == []
    finally:
        _cleanup(job_id)


def test_the_overwrite_argument_warns_and_changes_nothing(framework_job, rclone_calls):
    """overwrite= is accepted for one version and ignored."""
    job_id = "test_persistence_job_overwrite"
    DbManager.add_entry(_job_row(job_id))

    try:
        with pytest.warns(DeprecationWarning, match="overwrite"):
            job = Job(job_id=job_id, overwrite=True)

        assert job.job_id == job_id
        assert rclone_calls == []
    finally:
        _cleanup(job_id)


def test_deleting_an_item_of_the_framework_job_removes_it_locally_and_remotely(
    framework_job,
):
    """delete_item goes through delete_files, whichever pod holds the local copy."""
    job_id = "test_persistence_job_delete_item"
    DbManager.add_entry(_job_row(job_id))
    _seed_remote(job_id, FILE_NAME, FRESH)

    try:
        Job(job_id=job_id).delete_item(FILE_NAME)

        assert FILE_NAME not in {os.path.basename(f) for f in _remote_files(job_id)}
    finally:
        _cleanup(job_id)


def test_a_served_picture_and_download_are_current_when_the_local_copy_was_stale(
    framework_job,
):
    """serve_files fetches through work_dir, so a stale local file never wins."""
    job_id = "test_persistence_job_served"
    DbManager.add_entry(_job_row(job_id))
    _seed_remote(job_id, FILE_NAME, FRESH)
    _write(job_id, FILE_NAME, STALE)
    app = dash.Dash(__name__)
    app.layout = dash.html.Div()
    serve_files(app)
    client = app.server.test_client()

    try:
        picture = client.get(f"/pictures/{job_id}/{FILE_NAME}")
        _write(job_id, FILE_NAME, STALE)
        download = client.get(f"/download/{job_id}.zip")

        assert picture.data == FRESH.encode()
        with zipfile.ZipFile(io.BytesIO(download.data)) as archive:
            assert archive.read(FILE_NAME) == FRESH.encode()
    finally:
        _cleanup(job_id)


def test_submitting_the_framework_job_saves_before_the_enqueue_and_only_the_status_after(
    framework_job, rclone_calls, monkeypatch
):
    """The worker may already write files once enqueued, so nothing is synced then."""
    job_id = "test_persistence_job_submit"
    DbManager.add_entry(_job_row(job_id))
    _write(job_id, FILE_NAME, FRESH)
    seen = {}

    def handler(job):
        seen["remote_files"] = _remote_files(job_id)
        seen["row"] = load_row(job_id)
        seen["calls_at_enqueue"] = len(rclone_calls)
        return "task-id", False

    monkeypatch.setattr(Job, "submit_handler", staticmethod(handler))

    try:
        Job(job_id=job_id).submit()

        assert seen["remote_files"] == {FILE_NAME}
        assert seen["row"]["submitted"] is True
        assert len(rclone_calls) == seen["calls_at_enqueue"]
        assert load_row(job_id)["status"] == "RUNNING"
    finally:
        _cleanup(job_id)


def test_pull_file_replaces_a_stale_local_file_with_one_rclone_transfer(rclone_calls):
    """The hot read path: one file, remote wins, one transfer call.

    run_rclone_with_retry is counted once per transfer; its connection check
    (``rclone lsd``) is a separate subprocess it starts itself, so the transfer
    makes two rclone subprocesses in total. The command is ``rclone copy`` of
    the one file's directory, not ``copyto``, which fails on a missing source.
    """
    job_id = "test_persistence_pull_file"
    _write(job_id, FILE_NAME, FRESH)
    _write(job_id, "other.csv", FRESH)
    save_files(job_id)
    shutil.rmtree(_dir(job_id))
    _write(job_id, FILE_NAME, STALE)
    _write(job_id, "other.csv", STALE)
    rclone_calls.clear()

    try:
        path = pull_file(job_id, FILE_NAME)

        assert path == os.path.join(_dir(job_id), FILE_NAME)
        assert _read(job_id, FILE_NAME) == FRESH
        assert _read(job_id, "other.csv") == STALE
        assert [call[1] for call in rclone_calls] == ["copy"]
    finally:
        _cleanup(job_id)


def test_pull_file_fetches_a_file_in_a_subdirectory_whose_name_has_glob_characters():
    """The filter matches the name itself, not as a pattern."""
    job_id = "test_persistence_pull_file_nested"
    name = os.path.join("plots", "[a]*.csv")
    _write(job_id, name, FRESH)
    _write(job_id, os.path.join("plots", "ab.csv"), FRESH)
    save_files(job_id)
    shutil.rmtree(_dir(job_id))

    try:
        path = pull_file(job_id, name)

        assert _read(job_id, name) == FRESH
        assert os.listdir(os.path.dirname(path)) == ["[a]*.csv"]
    finally:
        _cleanup(job_id)


def test_pull_file_of_a_file_the_remote_lacks_keeps_the_local_copy(rclone_calls):
    """Missing remotely is not an error: the caller checks whether the path exists."""
    job_id = "test_persistence_pull_file_missing"
    _write(job_id, FILE_NAME, STALE)

    try:
        path = pull_file(job_id, FILE_NAME)

        assert path == os.path.join(_dir(job_id), FILE_NAME)
        assert _read(job_id, FILE_NAME) == STALE
        assert pull_file(job_id, "never_existed.csv") == os.path.join(
            _dir(job_id), "never_existed.csv"
        )
        assert not os.path.exists(os.path.join(_dir(job_id), "never_existed.csv"))
    finally:
        _cleanup(job_id)
