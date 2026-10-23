"""Job run: one execution of a job's computation on a worker, known by job id.

``run`` wraps an app's computation and does everything around it: it captures
the job log, fetches the work dir, uploads the results and writes the final
status to the job row. The job row is the only source of a job's status
(ADR 0002), so every failure ends as FAILED in the row and is not re-raised.
"""

import logging
from collections.abc import Callable

from cosmo_ecosystem import job_log, job_persistence
from cosmo_ecosystem.error_handling import JobNotFound
from cosmo_ecosystem.job_log import JobLogHandler

log = logging.getLogger(__name__)


def run(
    job_id: str,
    compute: Callable[[str, str], None],
    excluded_packages=(),
) -> str:
    """Run compute for the job and return the final status the row now holds.

    Clears the job log and captures every record logged during the run into
    it, writes RUNNING, fetches the work dir, calls
    ``compute(job_id, work_dir)``, uploads the work dir and writes COMPLETED,
    the row last. ``compute`` loads the app's own job, computes, writes its
    outputs into the work dir, signals failure only by raising, and never
    writes the status itself.

    Any exception ends the run as FAILED, logged with its traceback to the job
    log and the worker log; nothing is raised. A job without a row returns
    FAILED and writes nothing. A failed upload leaves the row RUNNING.

    Args:
        job_id: The job to run.
        compute: The app's computation, ``compute(job_id, work_dir) -> None``.
        excluded_packages: Extra packages to keep out of the job log, in
            addition to DEFAULT_EXCLUDED_PACKAGES — see ExcludeSubmodulesFilter.
    """
    job_log.clear(job_id)
    handler = JobLogHandler(job_id, excluded_packages=excluded_packages)
    root = logging.getLogger()
    # The handler sees only what the root level lets through. The worker's
    # logging config sets DEBUG, but a run must not depend on it.
    root_level = root.level
    root.setLevel(min(root_level, logging.DEBUG))
    root.addHandler(handler)
    try:
        log.info(f"Start the job run of job {job_id}.")
        job_persistence.update_columns(job_id, {"status": "RUNNING"})
        work_dir = job_persistence.work_dir(job_id)
        compute(job_id, work_dir)
        job_persistence.upload_work_dir(job_id)
        job_persistence.update_columns(job_id, {"status": "COMPLETED"})
        log.info(f"Job {job_id} completed.")
        return "COMPLETED"
    except Exception:  # noqa: BLE001
        # Convention exception (CLAUDE.md: specific exceptions only): compute is
        # any app's code and may raise anything, and the run must turn every
        # failure into FAILED in the row, or the job hangs in RUNNING forever.
        log.error(f"Job run of job {job_id} failed.", exc_info=True)
        _write_failed(job_id)
        return "FAILED"
    finally:
        root.removeHandler(handler)
        root.setLevel(root_level)
        handler.close()


def _write_failed(job_id: str) -> None:
    """Write FAILED to the job's row; a job without a row is only logged."""
    try:
        job_persistence.update_columns(job_id, {"status": "FAILED"})
    except JobNotFound:
        log.error(f"Job {job_id} has no row; its FAILED status is not recorded.")
