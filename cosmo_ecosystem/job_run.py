"""Job run: one execution of a job's computation on a worker, known by job id.

``run`` wraps an app's computation and does everything around it: it captures
the job log, fetches the work dir, uploads the results and writes the final
status to the job row. The job row is the only source of a job's status
(ADR 0002), so every failure ends as FAILED in the row and is not re-raised.
"""

import logging
from collections.abc import Callable

from sqlalchemy.exc import SQLAlchemyError

from cosmo_ecosystem import job_log, job_persistence
from cosmo_ecosystem.db_manager import DbManager
from cosmo_ecosystem.error_handling import JobNotFound
from cosmo_ecosystem.job_log import JobLogHandler

log = logging.getLogger(__name__)


def mark_queued(job_id: str) -> None:
    """Queue a run in the job's row: RUNNING, and no heartbeat, in one update.

    The only place a run's row is queued. Call it before the enqueue (ADR 0002):
    the run claims exactly a RUNNING row without a heartbeat, so a submit that
    writes RUNNING itself leaves an old heartbeat behind, and its run is dropped.

    Raises:
        JobNotFound: If the job has no row.
    """
    DbManager.mark_queued(job_id)


def run(
    job_id: str,
    compute: Callable[[str, str], None],
    excluded_packages=(),
) -> str | None:
    """Run compute for the job and return the final status the row now holds.

    First claims the run: the row must be queued (RUNNING, no heartbeat, see
    ``mark_queued``), and the claim gives it its first heartbeat. A delivery
    that loses the claim (a redelivery of a live or lost run, a stale message
    after a reset, a message for a cancelled or deleted job) writes nothing,
    neither to the row nor to the job log, says so in one line of the worker
    log and returns ``None``; the caller skips its post-run work then.

    A won claim clears the job log and captures every record logged during the
    run into it, fetches the work dir, calls ``compute(job_id, work_dir)``,
    uploads the work dir and writes COMPLETED, the row last. ``compute`` loads
    the app's own job, computes, writes its outputs into the work dir, signals
    failure only by raising, and never writes the status itself.

    Any exception, clearing the job log included, ends the run as FAILED,
    logged with its traceback to the job log and the worker log; nothing is
    raised. The job log is flushed before the final status is written. If the
    claim itself fails (database down), the run tries to write FAILED; if the
    FAILED write fails too, the run says so in the worker log and returns
    FAILED. A
    failed upload ends FAILED, so COMPLETED never names files the remote
    prefix lacks.

    Args:
        job_id: The job to run.
        compute: The app's computation, ``compute(job_id, work_dir) -> None``.
        excluded_packages: Extra packages to keep out of the job log, in
            addition to DEFAULT_EXCLUDED_PACKAGES — see ExcludeSubmodulesFilter.
    """
    root = logging.getLogger()
    # Saved and restored around the run: this assumes Celery's prefork pool,
    # one job run per process at a time. A threaded pool would have runs
    # restore each other's level and see each other's records.
    root_level = root.level
    handler = None
    try:
        # The first write, before the job log is cleared: a lost claim must
        # not clear the job log of a live or lost run.
        if not DbManager.claim_run(job_id):
            log.warning(
                f"Drop this delivery of job {job_id}: its row is not a queued "
                "run (already claimed, reset, cancelled or deleted)."
            )
            return None
        # Inside the guard: if the database fails even here, the run still
        # ends FAILED. The handler goes on before the load and the
        # computation, so their failures land in the job log.
        job_log.clear(job_id)
        handler = JobLogHandler(job_id, excluded_packages=excluded_packages)
        # The handler sees only what the root level lets through. The worker's
        # logging config sets DEBUG, but a run must not depend on it.
        root.setLevel(min(root_level, logging.DEBUG))
        root.addHandler(handler)
        log.info(f"Start the job run of job {job_id}.")
        work_dir = job_persistence.work_dir(job_id)
        compute(job_id, work_dir)
        job_persistence.upload_work_dir(job_id)
        log.info(f"Job {job_id} completed.")
        # Written before the row, so a poll that sees the final status also
        # sees the job log's last records.
        handler.flush()
        job_persistence.update_columns(job_id, {"status": "COMPLETED"})
        return "COMPLETED"
    except Exception:  # noqa: BLE001
        # Convention exception (CLAUDE.md: specific exceptions only): compute is
        # any app's code and may raise anything, and the run must turn every
        # failure into FAILED in the row, or the job hangs in RUNNING forever.
        log.error(f"Job run of job {job_id} failed.", exc_info=True)
        if handler is not None:
            handler.flush()
        _write_failed(job_id)
        return "FAILED"
    finally:
        if handler is not None:
            root.removeHandler(handler)
            handler.close()
        root.setLevel(root_level)


def _write_failed(job_id: str) -> None:
    """Write FAILED to the job's row; if that fails too, tell the worker log."""
    try:
        job_persistence.update_columns(job_id, {"status": "FAILED"})
    except JobNotFound:
        log.error(f"Job {job_id} has no row; its FAILED status is not recorded.")
    except SQLAlchemyError:
        log.error(
            f"Job {job_id}: writing its FAILED status failed; the row may still "
            "say RUNNING.",
            exc_info=True,
        )
