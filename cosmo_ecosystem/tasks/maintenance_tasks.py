"""Maintenance tasks for periodic cleanup."""

import logging
from datetime import datetime, timedelta

from celery import Task

from cosmo_ecosystem.constants import LOG_RETENTION_DAYS
from cosmo_ecosystem.db_manager import DbManager
from cosmo_ecosystem.job_retention import clean_up_jobs

log = logging.getLogger(__name__)


class MaintenanceTask(Task):
    """Base class for maintenance tasks with custom error handling."""

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Handle task failure."""
        log.error(f"Maintenance task {task_id} failed: {exc}")
        log.error(f"Traceback: {einfo}")


def cleanup_task(self):
    """Celery task for periodic cleanup of old jobs and logs."""
    log.info("Start cleaning up.")
    # Logs first: job cleanup may raise JobCleanupFailed, and log retention in
    # a `finally` could replace that exception with its own and hide which
    # jobs failed. The failure's own log lines are new, so this never deletes them.
    log_cutoff = datetime.now() - timedelta(days=LOG_RETENTION_DAYS)
    log.info(f"Cleaning up logs older than {log_cutoff}")
    DbManager.delete_logs_older_than(log_cutoff)

    clean_up_jobs()
