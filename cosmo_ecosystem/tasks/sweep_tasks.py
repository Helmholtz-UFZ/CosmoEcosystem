"""The framework's sweep: lost job runs end FAILED (ADR 0004).

A job run refreshes its row's heartbeat while it computes
(``cosmo_ecosystem.job_run``). A run whose heartbeat stopped was killed: its
worker child or pod died (OOM, hard time limit, pod restart, admin kill) before
it could write a final status. The sweep ends it as FAILED, says why in its job
log, and never retries it; the user resets the job to run it again.
"""

import logging
from datetime import timedelta

from cosmo_ecosystem import job_log
from cosmo_ecosystem.db_manager import DbManager

log = logging.getLogger(__name__)

# How old a RUNNING row's heartbeat may get before its run counts as lost. Ten
# heartbeat intervals (job_run.HEARTBEAT_INTERVAL_SECONDS), so a busy database
# or a slow beat never fails a live run.
LOST_RUN_THRESHOLD = timedelta(minutes=10)

LOST_RUN_MESSAGE = (
    "Worker lost: no heartbeat since {heartbeat_at}; the run was killed (OOM, "
    "hard time limit, pod restart or admin kill) and is not retried. Reset the "
    "job to run it again."
)


def sweep_lost_runs(threshold: timedelta = LOST_RUN_THRESHOLD) -> list[str]:
    """End every lost job run as FAILED and say so in its job log.

    A lost job run is RUNNING with a heartbeat older than ``threshold``. A
    queued run has no heartbeat and is never swept, however long it waits.

    Args:
        threshold: How old a heartbeat may be before its run counts as lost.

    Returns:
        The ids of the jobs it failed.
    """
    swept = DbManager.fail_runs_without_heartbeat_since(threshold)
    for job_id, heartbeat_at in swept:
        message = LOST_RUN_MESSAGE.format(
            heartbeat_at=heartbeat_at.isoformat(sep=" ", timespec="seconds")
        )
        log.error(f"Job {job_id}: {message}")
        job_log.append(job_id, message, level=logging.ERROR)
    return [job_id for job_id, _heartbeat_at in swept]


def sweep_task(self):
    """Celery task: sweep lost job runs; scheduled by the framework every 5 min.

    Runs on queue ``maintenance`` and shares the worker's children with job
    runs, so with all of them busy it waits for a free one. A killed child is
    replaced at once, so the sweep runs then; that wait is accepted.

    Returns:
        The ids of the swept jobs, for the result backend and the worker page.
    """
    return sweep_lost_runs()
