"""Job retention: what deleting a job means."""

import logging
import shutil

from cosmo_ecosystem.config import JOB_WORK_DIR_TEMPLATE
from cosmo_ecosystem.db_manager import DbManager
from cosmo_ecosystem.error_handling import JobNotFound
from cosmo_ecosystem.object_storage_manager import delete_directory_from_storage

log = logging.getLogger(__name__)


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
