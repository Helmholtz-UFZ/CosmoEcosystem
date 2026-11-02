"""The framework's nightly cleanup of old jobs and logs."""

import logging
from dataclasses import asdict
from datetime import datetime, timedelta

from cosmo_ecosystem.db_manager import DbManager
from cosmo_ecosystem.domain import load_domain
from cosmo_ecosystem.job_retention import clean_up_jobs

log = logging.getLogger(__name__)


def cleanup_task(self):
    """Delete logs past the domain's retention, then every expired job.

    Scheduled by the framework (see ``cosmo_ecosystem.celery_app``).

    Returns:
        The job cleanup summary as a dict, for the result backend and the
        worker page.
    """
    log.info("Start cleaning up.")
    # Logs first: job cleanup may raise JobCleanupFailed, and log retention in
    # a `finally` could replace that exception with its own and hide which
    # jobs failed. The failure's own log lines are new, so this never deletes them.
    log_cutoff = datetime.now() - timedelta(days=load_domain().log_retention_days)
    log.info(f"Cleaning up logs older than {log_cutoff}")
    DbManager.delete_logs_older_than(log_cutoff)

    return asdict(clean_up_jobs())
