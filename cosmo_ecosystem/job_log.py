"""Job log: the log records of a job's latest job run, in the database.

The records live in the ``job_logs`` table, one row per record, so any pod can
read a job's log while its run is still going, without a shared disk. Storage
is structured; ``read`` formats the records as the job's log file used to look.

A ``JobLogHandler`` writes the records of one job. A database error while
writing must not abort a computation, so it is logged as a WARNING to the
worker log and the batch is dropped: the opposite of ``PostgreSQLHandler``,
for which the worker log is critical.
"""

import datetime
import logging
import threading

from sqlalchemy import insert
from sqlalchemy.exc import SQLAlchemyError

from cosmo_ecosystem.db_manager import DbManager, JobLogTable
from cosmo_ecosystem.logger import ExcludeSubmodulesFilter

log = logging.getLogger(__name__)

FLUSH_INTERVAL_SECONDS = 2.0
BATCH_SIZE = 100


class JobLogHandler(logging.Handler):
    """A log handler that writes records to the job log of one job.

    Records are buffered and written in one batch insert every
    ``FLUSH_INTERVAL_SECONDS`` or every ``BATCH_SIZE`` records, and always on
    ``flush`` and ``close``. A background thread does the timed writes, so a
    computation that logs nothing for a while still has its earlier records
    readable. Level DEBUG, behind ``ExcludeSubmodulesFilter``, which also keeps
    this module's own records out.
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
        # Not `_closed`: logging.Handler.close sets that attribute to True.
        self._stopped = threading.Event()
        self._flusher = threading.Thread(
            target=self._flush_periodically,
            name=f"job-log-{job_id}",
            daemon=True,
        )
        self._flusher.start()

    def emit(self, record):
        """Buffer the record; write the buffer once it holds BATCH_SIZE records."""
        self._buffer.append(
            {
                "job_id": self.job_id,
                "timestamp": datetime.datetime.fromtimestamp(record.created),
                "level": record.levelname,
                "module": record.module,
                # The message with its traceback, if any, as the log file had it.
                "message": self.format(record),
            }
        )
        if len(self._buffer) >= BATCH_SIZE:
            self.flush()

    def flush(self):
        """Write the buffered records in one insert; drop them on a database error.

        Holds the handler lock throughout, so batches land in the order they
        were logged and a record logged meanwhile waits for the next batch.
        """
        with self.lock:
            rows, self._buffer = self._buffer, []
            if not rows:
                return
            try:
                with DbManager.session_scope() as session:
                    session.execute(insert(JobLogTable), rows)
            except SQLAlchemyError as error:
                log.warning(
                    f"Dropped {len(rows)} job log records of job {self.job_id}: {error}"
                )

    def close(self):
        """Stop the timed writes, write what is left and close the handler."""
        self._stopped.set()
        self._flusher.join()
        self.flush()
        super().close()

    def _flush_periodically(self):
        """Write the buffer every FLUSH_INTERVAL_SECONDS until closed."""
        while not self._stopped.wait(FLUSH_INTERVAL_SECONDS):
            self.flush()


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
