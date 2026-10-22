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

from cosmo_ecosystem.config import JOB_WORK_DIR_TEMPLATE
from cosmo_ecosystem.db_manager import DbManager
from cosmo_ecosystem.object_storage_manager import get_files, upload_files

log = logging.getLogger(__name__)


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
    path = JOB_WORK_DIR_TEMPLATE.format(job_id=job_id)
    os.makedirs(path, exist_ok=True)
    get_files(job_id, overwrite=True)
    return path


def save(job_id: str, row: dict) -> None:
    """Upload the job's work dir, then write the row (insert or update).

    Files first, row second: the row is the commit signal, so it never points
    at files that are not in storage yet. The upload deletes nothing remote.

    Raises:
        ObjectStorageError: If the upload fails; no row is written then.
    """
    upload_files(job_id)
    DbManager.add_entry({**row, "job_id": job_id})
