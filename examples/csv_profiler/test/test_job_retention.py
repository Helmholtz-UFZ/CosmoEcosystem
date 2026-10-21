"""Test the framework's job retention against real Postgres and S3 servers."""

import datetime
import os
import shutil
import time

import pytest

from cosmo_ecosystem.config import (
    JOB_WORK_DIR_TEMPLATE,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_REMOTE_NAME,
)
from cosmo_ecosystem.constants import DAYS_DELETE_NOT_SUBMITTED, DAYS_DELETE_SUBMITTED
from cosmo_ecosystem.db_manager import DbManager
from cosmo_ecosystem.error_handling import JobCleanupFailed
from cosmo_ecosystem.job_retention import clean_up_jobs, delete_job
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


def _seed_row(job_id, *, days_old=0, submitted=False):
    """Insert a database row for job_id, started days_old days ago."""
    DbManager.add_entry(
        {
            "job_id": job_id,
            "start_date": datetime.date.today() - datetime.timedelta(days=days_old),
            "input_data": {},
            "submitted": submitted,
            "notified_end": False,
            "logs": "",
            "status": "PENDING",
            "version": "0.1.0",
        }
    )


def _seed_local(job_id):
    """Write a file into job_id's local work directory."""
    os.makedirs(_work_dir(job_id), exist_ok=True)
    _seed_local_file(_work_dir(job_id))


def _seed_local_file(directory):
    """Write this test's file into directory."""
    with open(os.path.join(directory, FILE_NAME), "w", encoding="UTF-8") as f_handle:
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


def _make_undeletable(job_id, tmp_path):
    """Turn job_id's local work dir into one that shutil.rmtree refuses.

    rmtree raises OSError on a symlink, for root as well; CI runs as root, so
    read-only permissions would not stop it.
    """
    shutil.rmtree(_work_dir(job_id), ignore_errors=True)
    target = tmp_path / job_id
    target.mkdir()
    os.symlink(target, _work_dir(job_id))


def _cleanup(job_id):
    """Remove whatever a failed test left behind for job_id."""
    delete_directory_from_storage(job_id)
    if os.path.islink(_work_dir(job_id)):
        os.unlink(_work_dir(job_id))
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


def test_cleanup_removes_expired_jobs_everywhere_and_keeps_live_ones():
    """Expiry follows the retention periods; live jobs are not touched."""
    expired = {
        "test_cleanup_expired_unsubmitted": {
            "days_old": DAYS_DELETE_NOT_SUBMITTED,
            "submitted": False,
        },
        "test_cleanup_expired_submitted": {
            "days_old": DAYS_DELETE_SUBMITTED,
            "submitted": True,
        },
    }
    live = {
        "test_cleanup_live_unsubmitted": {
            "days_old": DAYS_DELETE_NOT_SUBMITTED - 1,
            "submitted": False,
        },
        "test_cleanup_live_submitted": {
            "days_old": DAYS_DELETE_SUBMITTED - 1,
            "submitted": True,
        },
    }
    for job_id, row in {**expired, **live}.items():
        _seed_row(job_id, **row)
        _seed_remote(job_id)

    try:
        clean_up_jobs()

        for job_id in expired:
            assert not DbManager.check_existence(job_id)
            assert not os.path.exists(_work_dir(job_id))
            assert _remote_files(job_id) == set()
        for job_id in live:
            assert DbManager.check_existence(job_id)
            assert os.path.exists(_work_dir(job_id))
            assert _remote_files(job_id) == {FILE_NAME}
    finally:
        for job_id in {**expired, **live}:
            _cleanup(job_id)


def test_cleanup_removes_expired_jobs_this_pod_never_touched_from_storage():
    """Regression: remote deletion used to be keyed on this pod's local disk.

    An expired job whose files live only in S3, because another pod handled
    it, kept its objects forever.
    """
    job_id = "test_cleanup_expired_no_local"
    _seed_row(job_id, days_old=DAYS_DELETE_NOT_SUBMITTED)
    _seed_remote(job_id)
    shutil.rmtree(_work_dir(job_id))
    assert _remote_files(job_id) == {FILE_NAME}

    try:
        clean_up_jobs()

        assert not DbManager.check_existence(job_id)
        assert _remote_files(job_id) == set()
    finally:
        _cleanup(job_id)


def test_cleanup_never_deletes_a_remote_prefix_without_a_row():
    """Stage and prod share a bucket: a rowless prefix may be the other's job."""
    job_id = "test_cleanup_foreign_prefix"
    _seed_remote(job_id)
    shutil.rmtree(_work_dir(job_id))

    try:
        clean_up_jobs()

        assert _remote_files(job_id) == {FILE_NAME}
    finally:
        _cleanup(job_id)


def test_cleanup_removes_an_orphaned_local_dir_but_not_its_remote_prefix():
    """A rowless local dir goes from disk only; S3 is never keyed on it."""
    job_id = "test_cleanup_orphan_local"
    _seed_remote(job_id)
    two_hours_ago = time.time() - 2 * 60 * 60
    os.utime(_work_dir(job_id), (two_hours_ago, two_hours_ago))

    try:
        clean_up_jobs()

        assert not os.path.exists(_work_dir(job_id))
        assert _remote_files(job_id) == {FILE_NAME}
    finally:
        _cleanup(job_id)


def test_cleanup_keeps_a_young_orphaned_local_dir():
    """A brand-new job has its dir before its row; cleanup must not race it."""
    job_id = "test_cleanup_young_orphan"
    _seed_local(job_id)

    try:
        clean_up_jobs()

        assert os.path.exists(_work_dir(job_id))
    finally:
        _cleanup(job_id)


def test_one_failing_job_does_not_stop_the_cleanup_but_fails_the_run(tmp_path):
    """The other expired jobs still go; the run raises naming the failure."""
    failing_id = "test_cleanup_failing"
    other_id = "test_cleanup_other"
    for job_id in (failing_id, other_id):
        _seed_row(job_id, days_old=DAYS_DELETE_NOT_SUBMITTED)
        _seed_remote(job_id)
    _make_undeletable(failing_id, tmp_path)

    try:
        with pytest.raises(JobCleanupFailed) as raised:
            clean_up_jobs()

        assert raised.value.job_ids == [failing_id]
        assert DbManager.check_existence(failing_id)
        assert not DbManager.check_existence(other_id)
        assert _remote_files(other_id) == set()
    finally:
        for job_id in (failing_id, other_id):
            _cleanup(job_id)


def test_cleanup_reports_what_it_did():
    """The summary names deleted, kept and failed jobs and removed local dirs.

    Membership, not equality: rows other tests left behind are cleaned too.
    """
    expired_id = "test_cleanup_summary_expired"
    live_id = "test_cleanup_summary_live"
    orphan_id = "test_cleanup_summary_orphan"
    _seed_row(expired_id, days_old=DAYS_DELETE_NOT_SUBMITTED)
    _seed_row(live_id)
    _seed_local(orphan_id)
    two_hours_ago = time.time() - 2 * 60 * 60
    os.utime(_work_dir(orphan_id), (two_hours_ago, two_hours_ago))

    try:
        summary = clean_up_jobs()

        assert expired_id in summary.deleted_ids
        assert live_id in summary.kept_ids
        assert expired_id not in summary.kept_ids
        assert orphan_id in summary.removed_local_dirs
        assert summary.failed_ids == []
    finally:
        for job_id in (expired_id, live_id, orphan_id):
            _cleanup(job_id)


def test_cleaning_with_a_zero_day_period_removes_todays_unsubmitted_jobs():
    """The dashboard "Clean": drafts go at once, submitted jobs stay."""
    draft_id = "test_cleanup_clean_draft"
    submitted_id = "test_cleanup_clean_submitted"
    _seed_row(draft_id)
    _seed_row(submitted_id, submitted=True)

    try:
        clean_up_jobs(days_delete_not_submitted=0)

        assert not DbManager.check_existence(draft_id)
        assert DbManager.check_existence(submitted_id)
    finally:
        for job_id in (draft_id, submitted_id):
            _cleanup(job_id)


def test_an_undeletable_orphaned_local_dir_does_not_hide_job_failures(tmp_path):
    """Orphan removal failing must not skip the job report or the exception."""
    failing_id = "test_cleanup_failing_with_orphan"
    orphan_id = "test_cleanup_locked_orphan"
    _seed_row(failing_id, days_old=DAYS_DELETE_NOT_SUBMITTED)
    _seed_remote(failing_id)
    for job_id in (failing_id, orphan_id):
        _make_undeletable(job_id, tmp_path)
    two_hours_ago = time.time() - 2 * 60 * 60
    os.utime(_work_dir(orphan_id), (two_hours_ago, two_hours_ago))

    try:
        with pytest.raises(JobCleanupFailed) as raised:
            clean_up_jobs()

        assert raised.value.job_ids == [failing_id]
    finally:
        for job_id in (failing_id, orphan_id):
            _cleanup(job_id)
