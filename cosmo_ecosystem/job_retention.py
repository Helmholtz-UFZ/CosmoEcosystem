"""Job retention: when a job expires, and what deleting a job means."""

import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.exc import SQLAlchemyError

from cosmo_ecosystem.config import JOB_WORK_DIR_TEMPLATE, WEB_WORK_DIR
from cosmo_ecosystem.constants import DAYS_DELETE_NOT_SUBMITTED, DAYS_DELETE_SUBMITTED
from cosmo_ecosystem.db_manager import DbManager
from cosmo_ecosystem.error_handling import JobCleanupFailed, JobNotFound
from cosmo_ecosystem.object_storage_manager import (
    ObjectStorageError,
    delete_directory_from_storage,
)

log = logging.getLogger(__name__)

# Job.__init__ creates the work dir, uploads it and only then writes the row,
# so a brand-new job briefly has a dir and no row. Younger orphans are left
# alone so a cleanup in that window (the dashboard "Clean") cannot remove it.
ORPHAN_DIR_GRACE_SECONDS = 60 * 60


@dataclass
class CleanupSummary:
    """What one cleanup run did."""

    deleted_ids: list[str] = field(default_factory=list)
    kept_ids: list[str] = field(default_factory=list)
    failed_ids: list[str] = field(default_factory=list)
    removed_local_dirs: list[str] = field(default_factory=list)


def delete_job(job_id: str) -> None:
    """Delete a job everywhere: its remote prefix, local work dir and row.

    Works from any pod, and whatever part is already gone counts as deleted.
    The row goes last because it is the retry handle: if a storage step
    raises, the row survives and the job is still listed for deleting again.

    Raises:
        ObjectStorageError: If the remote prefix could not be deleted.
    """
    log.info(f"Delete job {job_id}.")
    # A missing prefix is not an error here, which is what makes a job that
    # never uploaded anything deletable (see "Gotchas" in object_storage.md).
    delete_directory_from_storage(job_id)
    try:
        shutil.rmtree(JOB_WORK_DIR_TEMPLATE.format(job_id=job_id))
    except FileNotFoundError:
        log.debug(f"Job {job_id} has no local work dir on this pod.")
    try:
        DbManager.delete_job(job_id)
    except JobNotFound:
        log.debug(f"Job {job_id} has no database row any more.")


def days_to_live(
    start_date: date,
    submitted: bool,
    days_delete_not_submitted: int = DAYS_DELETE_NOT_SUBMITTED,
    days_delete_submitted: int = DAYS_DELETE_SUBMITTED,
) -> int:
    """Return the days left before a job expires; zero or less means expired."""
    days_passed = (date.today() - start_date).days
    if submitted:
        return days_delete_submitted - days_passed
    return days_delete_not_submitted - days_passed


def clean_up_jobs(
    days_delete_not_submitted: int = DAYS_DELETE_NOT_SUBMITTED,
    days_delete_submitted: int = DAYS_DELETE_SUBMITTED,
) -> CleanupSummary:
    """Delete every expired job everywhere and report what was done.

    A job that fails to delete is logged and skipped so the others still go.

    Raises:
        JobCleanupFailed: After the run, if any expired job could not be deleted.
    """
    log.info("Start cleaning up jobs.")
    summary = CleanupSummary()
    for job_id, job_info in DbManager.list_jobs().items():
        remaining = days_to_live(
            job_info["start_date"],
            job_info["submitted"],
            days_delete_not_submitted,
            days_delete_submitted,
        )
        if remaining > 0:
            summary.kept_ids.append(job_id)
            continue
        try:
            delete_job(job_id)
        except (ObjectStorageError, OSError, SQLAlchemyError) as error:
            log.error(f"Could not delete expired job {job_id}: {error}", exc_info=True)
            summary.failed_ids.append(job_id)
        else:
            summary.deleted_ids.append(job_id)

    summary.removed_local_dirs = _remove_orphaned_local_dirs()

    # Every deleted job had its remote prefix removed, so that count is the
    # number of deleted jobs.
    log.info(
        f"Cleanup done: {len(summary.deleted_ids)} deleted with their remote "
        "prefixes, "
        f"{len(summary.kept_ids)} kept, {len(summary.failed_ids)} failed, "
        f"{len(summary.removed_local_dirs)} orphaned local dirs removed."
    )
    if summary.failed_ids:
        raise JobCleanupFailed(summary.failed_ids)
    return summary


def _remove_orphaned_local_dirs() -> list[str]:
    """Remove local work dirs that belong to no job row, from this disk only.

    Never touches object storage: a rowless local dir says nothing about the
    bucket, which another environment's database may share.

    Returns:
        The names of the removed dirs.
    """
    removed = []
    # Listed again, not reused from the expiry pass: rows deleted there are now
    # gone, and rows whose deletion failed are still here and keep their dir.
    job_ids = DbManager.list_jobs().keys()
    cutoff = time.time() - ORPHAN_DIR_GRACE_SECONDS
    try:
        dir_names = os.listdir(WEB_WORK_DIR)
    except FileNotFoundError:
        log.debug(f"No work dir {WEB_WORK_DIR} on this pod yet.")
        return removed
    for dir_name in dir_names:
        dir_path = os.path.join(WEB_WORK_DIR, dir_name)
        if not os.path.isdir(dir_path) or dir_name in job_ids:
            continue
        if os.path.getmtime(dir_path) > cutoff:
            log.debug(f"Keep young orphaned work dir {dir_name}.")
            continue
        log.debug(f"Remove orphaned local work dir {dir_name}.")
        try:
            shutil.rmtree(dir_path)
        except OSError as error:
            # Not a job failure: no row is lost, and the next run tries again.
            log.error(
                f"Could not remove orphaned local work dir {dir_name}: {error}",
                exc_info=True,
            )
            continue
        removed.append(dir_name)
    return removed
