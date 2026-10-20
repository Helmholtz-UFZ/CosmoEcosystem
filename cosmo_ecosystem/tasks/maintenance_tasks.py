"""Maintenance tasks for periodic cleanup."""

import logging
import os
import shutil
from datetime import date, datetime, timedelta

from celery import Task

from cosmo_ecosystem.config import WEB_WORK_DIR
from cosmo_ecosystem.constants import (
    DAYS_DELETE_NOT_SUBMITTED,
    DAYS_DELETE_SUBMITTED,
    LOG_RETENTION_DAYS,
)
from cosmo_ecosystem.object_storage_manager import delete_directory_from_storage
from cosmo_ecosystem.db_manager import DbManager

log = logging.getLogger(__name__)


def clean_up_jobs(
    days_delete_not_submitted=DAYS_DELETE_NOT_SUBMITTED,
    days_delete_submitted=DAYS_DELETE_SUBMITTED,
):
    """Delete jobs depending on their status and age."""
    log.info("Start cleaning up jobs.")
    kept_jobs = []

    job_end_of_life_not_submitted = date.today() - timedelta(
        days=days_delete_not_submitted
    )
    job_end_of_life_submitted = date.today() - timedelta(days=days_delete_submitted)

    for job_id, job_info in DbManager.list_jobs().items():
        submitted = job_info["submitted"]
        start_date = job_info["start_date"]
        log.debug(f"Check job {job_id}.")
        if not submitted and start_date <= job_end_of_life_not_submitted:
            log.debug(
                f"Job was not submit and is older than {days_delete_not_submitted} days.",  # noqa
            )
            DbManager.delete_job(job_id)
        elif start_date <= job_end_of_life_submitted:
            log.debug(
                f"Job older than {days_delete_submitted} days.",
            )
            DbManager.delete_job(job_id)
        else:
            log.debug("Job will be kept.")
            kept_jobs.append(job_id)

    # Delete directories locally
    log.debug("Clean up directories locally.")
    for dir_name in os.listdir(WEB_WORK_DIR):
        dir_path = os.path.join(WEB_WORK_DIR, dir_name)
        if os.path.isdir(dir_path) and dir_name not in kept_jobs:
            shutil.rmtree(dir_path)
            delete_directory_from_storage(dir_name)


class MaintenanceTask(Task):
    """Base class for maintenance tasks with custom error handling."""

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Handle task failure."""
        log.error(f"Maintenance task {task_id} failed: {exc}")
        log.error(f"Traceback: {einfo}")


def cleanup_task(self):
    """Celery task for periodic cleanup of old jobs and logs."""
    log.info("Start cleaning up.")
    clean_up_jobs()

    log_cutoff = datetime.now() - timedelta(days=LOG_RETENTION_DAYS)
    log.info(f"Cleaning up logs older than {log_cutoff}")
    DbManager.delete_logs_older_than(log_cutoff)
