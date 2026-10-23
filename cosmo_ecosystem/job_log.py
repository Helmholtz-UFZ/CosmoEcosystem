"""Job log: the log records of a job's latest job run, in the database.

The records live in the ``job_logs`` table, one row per record, so any pod can
read a job's log while its run is still going, without a shared disk. Storage
is structured; ``read`` formats the records as the job's log file used to look.

A ``JobLogHandler`` writes the records of one job. A failure while writing
must not abort a computation, so it is logged as a WARNING to the worker log
and the batch is dropped: the opposite of ``PostgreSQLHandler``, for which the
worker log is critical. ``append`` writes one record at once, for notes from
outside a job run.

The handler buffers for up to ``FLUSH_INTERVAL_SECONDS``. A run revoked with
terminate (SIGTERM, SIGKILL) never closes its handler, so up to that much of
the end of its job log is lost.
"""

import datetime
import logging
import os
import sys
import threading

from sqlalchemy import insert

from cosmo_ecosystem.db_manager import DbManager, JobLogTable
from cosmo_ecosystem.logger import ExcludeSubmodulesFilter

log = logging.getLogger(__name__)

FLUSH_INTERVAL_SECONDS = 2.0
BATCH_SIZE = 100
# How long ``close`` waits for the last write before it gives up on it.
CLOSE_TIMEOUT_SECONDS = 5.0


class JobLogHandler(logging.Handler):
    """A log handler that writes records to the job log of one job.

    Records are buffered and written in one batch insert by a background
    thread every ``FLUSH_INTERVAL_SECONDS`` or as soon as ``BATCH_SIZE``
    records are buffered, so a computation that logs nothing for a while still
    has its earlier records readable, and a log call never waits for the
    database. ``flush`` writes synchronously; ``close`` writes what is left.
    Level DEBUG, behind ``ExcludeSubmodulesFilter``, which also keeps this
    module's own records out.
    """

    def __init__(self, job_id: str, excluded_packages=()):
        """Bind the handler to job_id and start the timed writes.

        Args:
            job_id: The job whose job log the records go to.
            excluded_packages: Extra packages to mute, in addition to
                DEFAULT_EXCLUDED_PACKAGES — see ExcludeSubmodulesFilter.
        """
        super().__init__(level=logging.DEBUG)
        self.job_id = job_id
        # This module's own records, above all the WARNING about a dropped batch,
        # stay out: buffered, they would fail again with every batch of an outage.
        self.addFilter(ExcludeSubmodulesFilter((*excluded_packages, __name__)))
        self._buffer = []
        # Serialises the writes, so batches land in the order they were logged.
        # Taken before self.lock, never while holding it.
        self._write_lock = threading.Lock()
        # Not `_closed`: logging.Handler.close sets that attribute to True.
        self._stopped = threading.Event()
        self._full = threading.Event()
        self._flusher = threading.Thread(
            target=self._flush_periodically,
            name=f"job-log-{job_id}",
            daemon=True,
        )
        self._flusher.start()

    def emit(self, record):
        """Buffer the record; wake the writer once BATCH_SIZE records wait."""
        try:
            row = _row(
                self.job_id,
                datetime.datetime.fromtimestamp(record.created),
                record.levelname,
                record.module,
                # The message with its traceback, if any, as the log file had it.
                self.format(record),
            )
        except Exception:  # noqa: BLE001
            # Convention exception (CLAUDE.md: specific exceptions only): the
            # stdlib handler contract. A record any library logs with a broken
            # %-format must not fail the computation; handleError reports it.
            self.handleError(record)
            return
        # Called under self.lock (Handler.handle), which guards the buffer.
        self._buffer.append(row)
        if len(self._buffer) >= BATCH_SIZE:
            self._full.set()

    def flush(self):
        """Write the buffered records in one insert; drop them on any failure.

        The buffer is swapped under the handler lock and written outside it,
        so a log call never waits for the database.
        """
        with self._write_lock:
            with self.lock:
                rows, self._buffer = self._buffer, []
            if not rows:
                return
            try:
                with DbManager.session_scope() as session:
                    session.execute(insert(JobLogTable), rows)
            except Exception as error:  # noqa: BLE001
                # Convention exception (CLAUDE.md: specific exceptions only): a
                # failed write must neither abort the computation nor stop the
                # timed writes. Besides SQLAlchemyError, the driver raises
                # plain errors for some values (ValueError for a NUL byte).
                log.warning(
                    f"Dropped {len(rows)} job log records of job {self.job_id}: "
                    f"{error!r}"
                )

    def close(self):
        """Stop the timed writes, write what is left and close the handler.

        Waits at most CLOSE_TIMEOUT_SECONDS for the last write; a write still
        hanging then is abandoned with a WARNING to the worker log.
        """
        self._stopped.set()
        self._full.set()
        self._flusher.join(timeout=CLOSE_TIMEOUT_SECONDS)
        if self._flusher.is_alive():
            log.warning(
                f"The job log of job {self.job_id} was still being written after "
                f"{CLOSE_TIMEOUT_SECONDS} s; its last records may be lost."
            )
        super().close()

    def _flush_periodically(self):
        """Write the buffer every FLUSH_INTERVAL_SECONDS or when full, and at close."""
        while not self._stopped.is_set():
            self._full.wait(FLUSH_INTERVAL_SECONDS)
            self._full.clear()
            self.flush()
        self.flush()


def append(job_id: str, message: str, level: int = logging.INFO) -> None:
    """Write one record to the job's job log now, for notes from outside a job run.

    For example "run cancelled by user". The record's module is the caller's.
    A database error is raised to the caller.

    Args:
        job_id: The job whose job log gets the record.
        message: The record's message.
        level: The record's level, a ``logging`` level number.
    """
    # The caller's module, as a logger would record it in record.module.
    module = os.path.splitext(os.path.basename(sys._getframe(1).f_code.co_filename))[0]
    row = _row(
        job_id,
        datetime.datetime.now(),
        logging.getLevelName(level),
        module,
        message,
    )
    with DbManager.session_scope() as session:
        session.execute(insert(JobLogTable), [row])


def _row(job_id, timestamp, level, module, message):
    """Return one job_logs row."""
    return {
        "job_id": job_id,
        "timestamp": timestamp,
        "level": level,
        "module": module,
        "message": message,
    }


def read(job_id: str) -> str:
    """Return the job's log, one ``[asctime] LEVEL in module: message`` per record.

    Records are in the order they were written; an unknown job id gives "".
    """
    with DbManager.session_scope() as session:
        records = (
            session.query(JobLogTable)
            .filter(JobLogTable.job_id == job_id)
            .order_by(JobLogTable.id)
            .all()
        )
        return "".join(
            f"[{_asctime(record.timestamp)}] {record.level} in {record.module}: "
            f"{record.message}\n"
            for record in records
        )


def clear(job_id: str) -> None:
    """Delete every record of the job's log."""
    log.debug(f"Clear the job log of job {job_id}.")
    with DbManager.session_scope() as session:
        session.query(JobLogTable).filter(JobLogTable.job_id == job_id).delete(
            synchronize_session=False
        )


def _asctime(timestamp: datetime.datetime) -> str:
    """Format timestamp as logging's default asctime: 2026-10-23 14:05:09,123."""
    return f"{timestamp:%Y-%m-%d %H:%M:%S},{timestamp.microsecond // 1000:03d}"
