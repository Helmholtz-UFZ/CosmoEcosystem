"""Job run: one execution of a job's computation on a worker, known by job id.

``run`` wraps an app's computation and does everything around it: it captures
the job log, fetches the work dir, uploads the results and writes the final
status to the job row. The job row is the only source of a job's status
(ADR 0002), so every failure ends as FAILED in the row and is not re-raised.
"""

import logging
import threading
import uuid
from collections.abc import Callable

from sqlalchemy.exc import SQLAlchemyError

from cosmo_ecosystem import job_log, job_persistence
from cosmo_ecosystem.db_manager import DbManager
from cosmo_ecosystem.job_log import JobLogHandler

log = logging.getLogger(__name__)
# The heartbeat's own logger, kept out of the job log: a failed beat means the
# database is unreachable, and the job log is in that database.
heartbeat_log = logging.getLogger(f"{__name__}.heartbeat")

# How often a run refreshes its heartbeat. The sweep's threshold
# (tasks.sweep_tasks.LOST_RUN_THRESHOLD) must stay well above it.
HEARTBEAT_INTERVAL_SECONDS = 60.0
# How long the end of a run waits for a heartbeat write still in progress.
HEARTBEAT_STOP_TIMEOUT_SECONDS = 5.0


def mark_queued(job_id: str) -> bool:
    """Queue a run in the job's row, and say whether the row allowed it.

    The submit guard (ADR 0005) and the only place a run's row is queued: one
    conditional update from PENDING or FAILED to RUNNING that clears the
    heartbeat and the run id and sets ``submitted``. A job that is already
    RUNNING or COMPLETED is left untouched and False is returned, so of two
    concurrent submits exactly one gets True. Call it first in a submit, before
    the work dir pull, the save and the enqueue (ADR 0002): the run claims
    exactly a RUNNING row without a heartbeat.

    Returns:
        Whether the run was queued.

    Raises:
        JobNotFound: If the job has no row.
    """
    return DbManager.queue_run(job_id)


def mark_pending(job_id: str) -> bool:
    """Return the job's row to PENDING, and say whether the row allowed it.

    For a job reset, the counterpart of ``mark_queued``: one conditional update
    from PENDING, FAILED or COMPLETED that clears the heartbeat and the run id,
    so the row cannot look claimed when it is queued again. ``submitted`` stays.
    A RUNNING row is left untouched and False is returned: a reset cannot strand
    a live run. The caller shows a hint.

    Returns:
        Whether the row is PENDING now by this call.

    Raises:
        JobNotFound: If the job has no row.
    """
    return DbManager.reset_run(job_id)


CANCELLED_MESSAGE = "The job run was cancelled."


def mark_cancelled(job_id: str) -> bool:
    """Cancel the job's run in its row, and say whether there was one to cancel.

    One conditional update from RUNNING to FAILED, committed together with one
    job log line saying the run was cancelled (``CANCELLED_MESSAGE``). A job
    that is not RUNNING (PENDING, or a run that finished a moment earlier) is
    left untouched, its job log too, and False is returned. The caller revokes
    the Celery task first; this is only the row, because a terminated worker
    writes nothing (ADR 0002). A cancelled run that is still alive finds a row
    that is no longer RUNNING, so its heartbeat and final status apply to
    nothing.

    Returns:
        Whether a run was cancelled.

    Raises:
        JobNotFound: If the job has no row.
    """
    return DbManager.cancel_run(job_id, CANCELLED_MESSAGE)


def mark_start_failed(job_id: str) -> bool:
    """Fail a queued run that could not be enqueued, if it is still queued.

    For a submit whose enqueue failed after ``mark_queued`` won: FAILED is
    written only to a row that is still a queued run (RUNNING, no heartbeat),
    so a run a worker already claimed, or a row reset or cancelled meanwhile,
    is left alone.

    Returns:
        Whether the row was a queued run and is FAILED now.
    """
    return DbManager.fail_queued_run(job_id)


class _Heartbeat:
    """A daemon thread that refreshes a running job's heartbeat until stopped.

    Runs in the prefork child next to the computation. A failed write is
    logged to the worker log and retried on the next tick. It writes only while
    the row still carries the run's id; once the run is overtaken (cancelled,
    swept, reset, replaced by a newer run) it says so in the worker log and stops.
    """

    def __init__(self, job_id: str, run_id: uuid.UUID, interval: float):
        self.job_id = job_id
        self.run_id = run_id
        self.interval = interval
        self._stopped = threading.Event()
        self._thread = threading.Thread(
            target=self._beat, name=f"heartbeat-{job_id}", daemon=True
        )
        self._thread.start()

    def _beat(self):
        while not self._stopped.wait(self.interval):
            try:
                if not DbManager.refresh_heartbeat(self.job_id, self.run_id):
                    heartbeat_log.warning(
                        f"The run {self.run_id} of job {self.job_id} was "
                        "overtaken: its heartbeat is no longer written."
                    )
                    return
            except SQLAlchemyError as error:
                heartbeat_log.warning(
                    f"The heartbeat of job {self.job_id} failed and is retried "
                    f"in {self.interval} s: {error!r}"
                )

    def stop(self):
        """Stop the beats; wait a bounded time for a write still in progress."""
        self._stopped.set()
        self._thread.join(timeout=HEARTBEAT_STOP_TIMEOUT_SECONDS)


def run(
    job_id: str,
    compute: Callable[[str, str], None],
    excluded_packages=(),
    heartbeat_interval: float = HEARTBEAT_INTERVAL_SECONDS,
) -> str | None:
    """Run compute for the job and return the final status it wrote to the row.

    First claims the run: the row must be queued (RUNNING, no heartbeat, see
    ``mark_queued``), and the claim gives it its first heartbeat and a fresh
    run id. A delivery that loses the claim (a redelivery of a live or lost run,
    a stale message after a reset, a message for a cancelled or deleted job)
    writes nothing, neither to the row nor to the job log, says so in one line
    of the worker log and returns ``None``; the caller skips its post-run work
    then.

    A won claim clears the job log and captures every record logged during the
    run into it, fetches the work dir, calls ``compute(job_id, work_dir)``,
    uploads the work dir and writes COMPLETED, the row last. ``compute`` loads
    the app's own job, computes, writes its outputs into the work dir, signals
    failure only by raising, and never writes the status itself. From the
    claim to the end of the run, a daemon thread refreshes the row's heartbeat
    every ``heartbeat_interval`` seconds; the sweep ends a run whose heartbeat
    stopped as FAILED (ADR 0004).

    The run owns the row from its claim until its final status (ADR 0005): the
    heartbeat and the final status are written only while the row is RUNNING and
    still carries the run's id. A run that was overtaken (cancelled, swept as
    lost, reset or replaced by a newer run) writes nothing, says so in the worker
    log, and returns ``None``, like a dropped delivery: the row holds a status
    that is not its own, so the caller skips its post-run work (end mail,
    ``notified_end``) and reports no status.

    Any exception, clearing the job log included, ends the run as FAILED,
    logged with its traceback to the job log and the worker log; nothing is
    raised. The job log is flushed before the final status is written. If the
    claim itself fails (database error), the run writes FAILED only if the row
    is still queued, so a row another delivery claimed is left alone (the run
    returns ``None`` then, FAILED when it wrote it). If the FAILED write fails
    too, the run says so in the worker log and returns FAILED. A failed upload
    ends FAILED, so COMPLETED never names files the remote prefix lacks.

    Args:
        job_id: The job to run.
        compute: The app's computation, ``compute(job_id, work_dir) -> None``.
        excluded_packages: Extra packages to keep out of the job log, in
            addition to DEFAULT_EXCLUDED_PACKAGES — see ExcludeSubmodulesFilter.
        heartbeat_interval: Seconds between two heartbeats.

    Returns:
        ``"COMPLETED"`` or ``"FAILED"`` when the run wrote that status (or could
        not write FAILED because the database failed), ``None`` when it wrote
        nothing: a dropped delivery, an overtaken run, a failed claim on a row
        that was not queued.
    """
    root = logging.getLogger()
    # Saved and restored around the run: this assumes Celery's prefork pool,
    # one job run per process at a time. A threaded pool would have runs
    # restore each other's level and see each other's records.
    root_level = root.level
    handler = None
    heartbeat = None
    run_id = None
    try:
        # The first write, before the job log is cleared: a lost claim must
        # not clear the job log of a live or lost run. Claim, heartbeat and the
        # failed-claim write go to DbManager directly, not through
        # job_persistence: they are conditional updates whose result is the
        # point, and job_persistence.update_columns is the unconditional
        # column seam (it would overwrite whatever another delivery wrote).
        run_id = DbManager.claim_run(job_id)
        if run_id is None:
            log.warning(
                f"Drop this delivery of job {job_id}: its row is not a queued "
                "run (already claimed, reset, cancelled or deleted)."
            )
            return None
        heartbeat = _Heartbeat(job_id, run_id, heartbeat_interval)
        # Inside the guard: if the database fails even here, the run still
        # ends FAILED. The handler goes on before the load and the
        # computation, so their failures land in the job log.
        job_log.clear(job_id)
        handler = JobLogHandler(
            job_id, excluded_packages=(*excluded_packages, heartbeat_log.name)
        )
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
        return _end(job_id, run_id, "COMPLETED")
    except Exception:  # noqa: BLE001
        # Convention exception (CLAUDE.md: specific exceptions only): compute is
        # any app's code and may raise anything, and the run must turn every
        # failure into FAILED in the row, or the job hangs in RUNNING forever.
        log.error(f"Job run of job {job_id} failed.", exc_info=True)
        if handler is not None:
            handler.flush()
        if run_id is not None:
            return _write_failed(job_id, run_id)
        return _write_failed_if_queued(job_id)
    finally:
        if heartbeat is not None:
            heartbeat.stop()
        if handler is not None:
            root.removeHandler(handler)
            handler.close()
        root.setLevel(root_level)


def _end(job_id: str, run_id: uuid.UUID, status: str) -> str | None:
    """Write the run's final status; return it, or None if the run was overtaken."""
    if DbManager.end_run(job_id, run_id, status):
        return status
    log.warning(
        f"Job {job_id}: the run {run_id} was overtaken (cancelled, swept as "
        f"lost, reset, replaced by a newer run or deleted); its {status} status "
        "is not written."
    )
    return None


def _write_failed_if_queued(job_id: str) -> str | None:
    """After a failed claim: write FAILED only if the run is still queued.

    The claim may have failed after another delivery claimed the row, or its
    own update may even have committed; either way, a row with a heartbeat is
    a run someone computes, and the sweep watches it.

    Returns:
        ``"FAILED"`` when it wrote it, or when the write itself failed (the
        row may still say RUNNING); ``None`` when the row was not a queued run.
    """
    try:
        if DbManager.fail_queued_run(job_id):
            return "FAILED"
        log.warning(
            f"Job {job_id}: the claim failed and the row is not a queued run; "
            "it is left as it is."
        )
        return None
    except SQLAlchemyError:
        log.error(
            f"Job {job_id}: writing its FAILED status failed; the row may still "
            "say RUNNING.",
            exc_info=True,
        )
        return "FAILED"


def _write_failed(job_id: str, run_id: uuid.UUID) -> str | None:
    """Write FAILED to the run's row; if that fails too, tell the worker log.

    Returns:
        ``"FAILED"``, also when the database failed (the row may still say
        RUNNING); ``None`` when the run was overtaken and wrote nothing.
    """
    try:
        return _end(job_id, run_id, "FAILED")
    except SQLAlchemyError:
        log.error(
            f"Job {job_id}: writing its FAILED status failed; the row may still "
            "say RUNNING.",
            exc_info=True,
        )
        return "FAILED"
