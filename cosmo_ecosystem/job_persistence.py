"""Job persistence: a job's row, work dir and remote prefix, known by id only.

The remote prefix is authoritative and the work dir a cache (ADR 0001): reading
files pulls what changed and never deletes locally, saving uploads without
deleting remotely. The module is column-agnostic: it reads and writes whatever
columns a dict carries, against ``DbManager.job_table``.

Live logs during a run are not persisted here: polls read the log file from
local disk, which works only while web and worker share a work dir. Moving job
logs to the database is a later step.
"""

import logging
import os
import shutil

from sqlalchemy.exc import SQLAlchemyError

from cosmo_ecosystem.config import JOB_WORK_DIR_TEMPLATE
from cosmo_ecosystem.db_manager import DbManager
from cosmo_ecosystem.error_handling import JobDeletionFailed, JobNotFound
from cosmo_ecosystem.object_storage_manager import (
    ObjectStorageError,
    delete_directory_from_storage,
    delete_file_from_storage,
    get_file,
    get_files,
    upload_files,
)

log = logging.getLogger(__name__)


def local_dir(job_id: str) -> str:
    """Return the path of the job's local work dir. Pure: no rclone, no mkdir."""
    return JOB_WORK_DIR_TEMPLATE.format(job_id=job_id)


def load_row(job_id: str) -> dict:
    """Return the job's row as a dict. Reads the database only, no rclone call.

    Raises:
        JobNotFound: If the job has no row.
    """
    return DbManager.get_job_columns(job_id)


def update_columns(job_id: str, columns: dict) -> None:
    """Write only the given columns of the job's row. No rclone call.

    Raises:
        JobNotFound: If the job has no row.
    """
    DbManager.update_column(job_id, columns)


def work_dir(job_id: str) -> str:
    """Return the job's local work dir, current with its remote prefix.

    Creates the dir and pulls the files whose checksum differs from the remote
    copy (the remote prefix wins). Local files the remote lacks are kept, so a
    running worker's outputs on a shared disk survive a pull.

    Raises:
        ObjectStorageError: If the download fails.
    """
    path = local_dir(job_id)
    os.makedirs(path, exist_ok=True)
    get_files(job_id, overwrite=True)
    return path


def pull_file(job_id: str, path: str) -> str:
    """Make one file of the job current with its remote copy; return its local path.

    For read paths too hot for a full ``work_dir`` pull: one
    ``rclone copyto --checksum``, the remote prefix wins (ADR 0001). Path is
    relative to the work dir. If the remote has no such file nothing happens and
    no error is raised: a local copy is kept as it is, and the returned path may
    not exist, so the caller checks ``os.path.exists`` on it.

    Raises:
        ObjectStorageError: If the download fails for another reason.
    """
    get_file(job_id, path)
    return os.path.join(local_dir(job_id), path)


def upload_work_dir(job_id: str) -> None:
    """Upload the job's work dir to its remote prefix; write no row.

    ``rclone copy --checksum``: new and changed files go up, remote files the
    work dir lacks stay (ADR 0001). Afterwards every local file must be in the
    remote prefix. For a caller that writes the row itself, after the upload,
    such as a job run writing its final status.

    Raises:
        ObjectStorageError: If the upload fails or a local file is missing
            remotely afterwards.
    """
    # A pod that never held the files has no dir; uploading it is a no-op.
    os.makedirs(local_dir(job_id), exist_ok=True)
    upload_files(job_id)


def save(job_id: str, row: dict) -> None:
    """Upload the job's work dir, then write the row (insert or update).

    Files first, row second: the row is the commit signal, so it never points
    at files that are not in storage yet. The upload deletes nothing remote.

    Raises:
        ObjectStorageError: If the upload fails; no row is written then.
    """
    upload_work_dir(job_id)
    DbManager.add_entry({**row, "job_id": job_id})


def delete_files(job_id: str, paths: list[str]) -> None:
    """Delete files or dirs from the job's work dir and its remote prefix.

    Paths are relative to the work dir. Both sides are deleted in this call,
    because a later upload deletes nothing remote (ADR 0001) and a later pull
    would bring a remote leftover back. Whatever is already gone on either
    side counts as deleted.

    Raises:
        ObjectStorageError: If the remote deletion fails.
    """
    for path in paths:
        log.info(f"Delete {path} of job {job_id}.")
        # ``rclone delete`` removes a single object or every object below a
        # prefix, and succeeds on a missing path.
        delete_file_from_storage(f"{job_id}/{path}")
        local_path = os.path.join(local_dir(job_id), path)
        try:
            shutil.rmtree(local_path)
        except NotADirectoryError:
            os.remove(local_path)
        except FileNotFoundError:
            log.debug(f"{path} of job {job_id} is not in the local work dir.")


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
        shutil.rmtree(local_dir(job_id))
    except FileNotFoundError:
        log.debug(f"Job {job_id} has no local work dir on this pod.")
    try:
        DbManager.delete_job(job_id)
    except JobNotFound:
        log.debug(f"Job {job_id} has no database row any more.")


def delete_jobs(job_ids: list[str]) -> None:
    """Delete every job in job_ids everywhere; one failure does not stop the rest.

    The dashboard "Delete" on a multi-row selection.

    Raises:
        JobDeletionFailed: After all jobs were tried, naming those that could
            not be deleted. They keep their row and can be deleted again.
    """
    failed_ids = delete_jobs_returning_failures(job_ids)
    if failed_ids:
        raise JobDeletionFailed(failed_ids)


def delete_jobs_returning_failures(job_ids: list[str]) -> list[str]:
    """Delete each job, logging and skipping failures; return the failed ids."""
    failed_ids = []
    for job_id in job_ids:
        try:
            delete_job(job_id)
        except (ObjectStorageError, OSError, SQLAlchemyError) as error:
            log.error(f"Could not delete job {job_id}: {error}", exc_info=True)
            failed_ids.append(job_id)
    return failed_ids
