"""Module for interaction between webservice and database."""

import logging
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    String,
    Text,
    create_engine,
    delete,
    func,
    insert,
    update,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from cosmo_ecosystem.config import (
    POSTGRES_DB,
    POSTGRES_HOST_NAME,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from cosmo_ecosystem.error_handling import JobNotFound, JobTableNotConfigured

log = logging.getLogger(__name__)

# The columns only the job run's named transitions write (ADR 0005): never a save.
# ``add_entry`` skips them when it updates an existing row.
RUN_OWNED_COLUMNS = ("heartbeat_at", "run_id", "status", "submitted")


class Base(DeclarativeBase):
    """The framework's declarative registry — the one every table belongs on.

    This is a documented export point, not an internal detail. An app declares
    its own tables on this ``Base``::

        from cosmo_ecosystem.db_manager import Base

        class RouteTable(Base):
            __tablename__ = "routes"
            ...

    Why it matters: a second ``DeclarativeBase`` in the same process means a
    second mapper registry and, with it, a second engine and connection pool
    against the same database. Both apps run exactly that today — their own
    ``Base`` next to this one, each mapping ``logs`` and ``jobs`` — and it works
    only because ``DbManager`` here is confined to the framework pages' log
    queries. Sharing this ``Base`` and this engine is what Slice 2 unwinds
    app-side. See docs/conventions/database_schema.md.
    """

    pass


class SessionScope:
    """Context manager for managing database sessions with retry logic."""

    def __init__(self, session_factory):
        """Initialize the session scope with a session factory."""
        self.session_factory = session_factory
        self.max_retries = 3
        self.retry_delay = 1
        self.session = None

    def __enter__(self):
        """Create a new session and handle retries for database operations."""
        for attempt in range(self.max_retries + 1):
            try:
                self.session = self.session_factory()
                return self.session  # success
            except OperationalError as e:
                if attempt < self.max_retries:
                    log.warning(f"Database OperationalError: {e}")
                    log.warning(
                        f"Retrying operation (attempt {attempt + 1}/{self.max_retries + 1})"  # noqa
                    )
                    time.sleep(self.retry_delay)
                else:
                    log.error(f"Max retries ({self.max_retries}) exceeded")
                    raise
            except SQLAlchemyError as e:
                log.error(f"Database error: {e}")
                raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Commit or rollback the session based on exception type."""
        try:
            if exc_type is None:
                self.session.commit()
            else:
                self.session.rollback()
        finally:
            self.session.close()

        # False means exceptions are re-raised outside the `with`
        return False


class DbManager:
    """Class for interacting with the postgres database.

    ``job_table`` is the app's seam for the job methods below: assign the app's
    concrete ``JobColumns`` subclass to it before any of them run. It must be
    set on ``DbManager`` itself, not on a subclass — framework pages call
    ``DbManager.list_jobs()`` directly, so ``cls`` there is always the base
    class, and a subclass assignment configures only the app's own call sites.
    See docs/conventions/database_schema.md.
    """

    _engine = None
    _Session = None
    job_table = None

    @classmethod
    def _job_table(cls):
        """Return the app's job table class, or fail loudly if unset."""
        if cls.job_table is None:
            raise JobTableNotConfigured()
        return cls.job_table

    @classmethod
    def _get_session(cls):
        """Return the session factory, creating the engine on first call."""
        if cls._Session is None:
            database_url = (
                f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}@"
                f"{POSTGRES_HOST_NAME}:{POSTGRES_PORT}/{POSTGRES_DB}"
            )
            cls._engine = create_engine(
                database_url,
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=10,
                pool_timeout=30,
                pool_recycle=1800,
            )
            cls._Session = sessionmaker(bind=cls._engine)
        return cls._Session

    @classmethod
    def session_scope(cls):
        """Provide a transactional scope around a series of operations."""
        return SessionScope(session_factory=cls._get_session())

    @classmethod
    def query_distinct_modules(cls) -> List[str]:
        """Return all distinct module names from the logs table.

        Returns
        -------
        list[str]
            Sorted list of unique module names.
        """
        with cls.session_scope() as session:
            rows = (
                session.query(LogTable.module)
                .distinct()
                .order_by(LogTable.module)
                .all()
            )
            return [row[0] for row in rows]

    @classmethod
    def query_logs(
        cls,
        date: str,
        sh: int,
        sm: int,
        eh: int,
        em: int,
        levels: List[str],
        pid: Optional[int] = None,
        excluded_modules: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Query logs from the database with specified filters.

        Parameters
        ----------
        date : str
            Date in the format 'YYYY-MM-DD'
        sh : int
            Start hour (0-23)
        sm : int
            Start minute (0-59)
        eh : int
            End hour (0-23)
        em : int
            End minute (0-59)
        levels : list
            List of log levels to include (e.g., ['INFO', 'ERROR'])
        pid : int, optional
            Process ID to filter logs by
        excluded_modules : list[str], optional
            Module names to exclude from results
        """
        log.debug(f"Querying logs from {date} {sh}:{sm} to {date} {eh}:{em}")

        start_datetime = datetime.strptime(
            f"{date} {sh:02d}:{sm:02d}:00", "%Y-%m-%d %H:%M:%S"
        )
        end_datetime = datetime.strptime(
            f"{date} {eh:02d}:{em:02d}:59", "%Y-%m-%d %H:%M:%S"
        )

        with cls.session_scope() as session:
            query = session.query(LogTable).filter(
                LogTable.timestamp >= start_datetime,
                LogTable.timestamp <= end_datetime,
                LogTable.level.in_(levels),
            )

            if pid is not None:
                query = query.filter(LogTable.pid == pid)

            if excluded_modules:
                query = query.filter(LogTable.module.notin_(excluded_modules))

            # Order results by timestamp
            query = query.order_by(LogTable.timestamp)

            # Execute query and convert results to dictionaries
            logs = [log.to_dict() for log in query.all()]

        return logs

    @classmethod
    def delete_logs_older_than(cls, cutoff_datetime):
        """Delete all log records older than the given datetime."""
        log.info(f"Deleting logs older than {cutoff_datetime}")
        with cls.session_scope() as session:
            session.query(LogTable).filter(LogTable.timestamp < cutoff_datetime).delete(
                synchronize_session=False
            )

    @classmethod
    def check_existence(cls, job_id):
        """Check if a job with the given job ID exists in the database."""
        log.debug(f"Check existence of job: {job_id}")
        job_table = cls._job_table()
        with cls.session_scope() as session:
            job_row = session.query(job_table.job_id).filter_by(job_id=job_id).first()
        return job_row is not None

    @classmethod
    def add_entry(cls, data_to_insert):
        """Create a job's row, or update an existing one without its run's columns.

        A new row starts PENDING and not submitted unless ``data_to_insert``
        says otherwise (a fixture, a restore). An existing row gets every
        column of ``data_to_insert`` except ``RUN_OWNED_COLUMNS``: a save never
        writes status, submitted, heartbeat or run id, so a job object loaded
        earlier cannot put an old state back (ADR 0005). Those change only
        through the named transitions of ``cosmo_ecosystem.job_run``.
        """
        log.debug(
            f"Add entry to database: {data_to_insert['job_id']}",
        )
        job_table = cls._job_table()
        with cls.session_scope() as session:
            job_row = (
                session.query(job_table.job_id)
                .filter_by(job_id=data_to_insert["job_id"])
                .first()
            )

            if job_row is not None:
                log.debug("Update entry.")
                job = (
                    session.query(job_table)
                    .filter_by(job_id=data_to_insert["job_id"])
                    .first()
                )
                for column_name, column_value in data_to_insert.items():
                    if column_name not in RUN_OWNED_COLUMNS:
                        setattr(job, column_name, column_value)
            else:
                log.debug("New entry.")
                job_row = job_table(
                    **{"status": "PENDING", "submitted": False, **data_to_insert}
                )
                session.add(job_row)

    @classmethod
    def update_column(cls, job_id, column_dic):
        """Update specific columns of the job table for a given job ID."""
        log.debug(f"Update columns for job: {job_id}")

        job_table = cls._job_table()
        with cls.session_scope() as session:
            job = session.query(job_table).filter_by(job_id=job_id).first()
            if job is None:
                raise JobNotFound(job_id)

            for column_name, column_value in column_dic.items():
                setattr(job, column_name, column_value)

    @classmethod
    def update_input(cls, job_id, columns) -> bool:
        """Write a job's input columns, only while the job is PENDING.

        One conditional update (``WHERE status = 'PENDING'``). For an existing
        row it is how input is written: a page or task holding an old copy of
        the job cannot change the input of a job that started, finished or was
        reset meanwhile (ADR 0005). It writes the given input columns and
        nothing else: never ``start_date`` and never ``RUN_OWNED_COLUMNS``.

        Args:
            job_id: The job whose input to write.
            columns: Column name to value, input columns only.

        Returns:
            Whether the row was PENDING and the columns were written.

        Raises:
            ValueError: If ``columns`` names ``job_id``, ``start_date`` or a
                run-owned column.
            JobNotFound: If the job has no row.
        """
        not_input = {"job_id", "start_date", *RUN_OWNED_COLUMNS} & set(columns)
        if not_input:
            raise ValueError(
                f"Not input columns of job {job_id}: {', '.join(sorted(not_input))}."
            )
        log.debug(f"Update the input of job: {job_id}")
        job_table = cls._job_table()
        with cls.session_scope() as session:
            result = session.execute(
                update(job_table)
                .where(job_table.job_id == job_id, job_table.status == "PENDING")
                .values(**columns)
            )
            applied = result.rowcount == 1
        if not applied:
            cls._raise_if_no_row(job_id)
        return applied

    @classmethod
    def queue_run(cls, job_id) -> bool:
        """Queue a run in the job's row; return whether the row allowed it.

        One conditional update from PENDING or FAILED to RUNNING that clears the
        heartbeat and the run id and sets ``submitted``; of any number of
        concurrent callers at most one gets True.

        Raises:
            JobNotFound: If the job has no row.
        """
        log.debug(f"Queue a run of job: {job_id}")
        job_table = cls._job_table()
        with cls.session_scope() as session:
            result = session.execute(
                update(job_table)
                .where(
                    job_table.job_id == job_id,
                    job_table.status.in_(("PENDING", "FAILED")),
                )
                .values(
                    status="RUNNING",
                    heartbeat_at=None,
                    run_id=None,
                    submitted=True,
                )
            )
            applied = result.rowcount == 1
        if not applied:
            cls._raise_if_no_row(job_id)
        return applied

    @classmethod
    def _raise_if_no_row(cls, job_id):
        """Raise JobNotFound if the job has no row: a refused update says why."""
        if not cls.check_existence(job_id):
            raise JobNotFound(job_id)

    @classmethod
    def reset_run(cls, job_id) -> bool:
        """Return the job's row to PENDING; return whether the row allowed it.

        One conditional update from PENDING, FAILED or COMPLETED that clears the
        heartbeat and the run id. ``submitted`` stays: it means "submitted at
        least once". A RUNNING row is left untouched.

        Raises:
            JobNotFound: If the job has no row.
        """
        log.debug(f"Reset the row of job: {job_id}")
        job_table = cls._job_table()
        with cls.session_scope() as session:
            result = session.execute(
                update(job_table)
                .where(
                    job_table.job_id == job_id,
                    job_table.status.in_(("PENDING", "FAILED", "COMPLETED")),
                )
                .values(status="PENDING", heartbeat_at=None, run_id=None)
            )
            applied = result.rowcount == 1
        if not applied:
            cls._raise_if_no_row(job_id)
        return applied

    @classmethod
    def cancel_run(cls, job_id, message) -> bool:
        """Fail the job's RUNNING row and log message to its job log, in one commit.

        One conditional update from RUNNING to FAILED. The job log record is
        inserted in the same transaction, so a database error between the two
        leaves neither. Heartbeat and run id stay: the cancelled run's own
        writes find a row that is no longer RUNNING.

        Returns:
            Whether the row was RUNNING. A row in any other status is untouched.

        Raises:
            JobNotFound: If the job has no row.
        """
        log.debug(f"Cancel the run of job: {job_id}")
        job_table = cls._job_table()
        with cls.session_scope() as session:
            result = session.execute(
                update(job_table)
                .where(job_table.job_id == job_id, job_table.status == "RUNNING")
                .values(status="FAILED")
            )
            applied = result.rowcount == 1
            if applied:
                session.execute(
                    insert(JobLogTable),
                    [
                        {
                            "job_id": job_id,
                            "timestamp": datetime.now(),
                            "level": "WARNING",
                            "module": "job_run",
                            "message": message,
                        }
                    ],
                )
        if not applied:
            cls._raise_if_no_row(job_id)
        return applied

    @classmethod
    def claim_run(cls, job_id) -> uuid.UUID | None:
        """Give a queued run's row its first heartbeat and a fresh run id.

        One conditional update (``status = 'RUNNING' AND heartbeat_at IS NULL``),
        so of any number of concurrent callers at most one wins.

        Returns:
            The new run id, or None if the row was not a queued run.
        """
        run_id = uuid.uuid4()
        job_table = cls._job_table()
        with cls.session_scope() as session:
            result = session.execute(
                update(job_table)
                .where(
                    job_table.job_id == job_id,
                    job_table.status == "RUNNING",
                    job_table.heartbeat_at.is_(None),
                )
                .values(heartbeat_at=func.now(), run_id=run_id)
            )
            return run_id if result.rowcount == 1 else None

    @classmethod
    def fail_queued_run(cls, job_id) -> bool:
        """Write FAILED to the job's row if its run is still queued; return whether.

        Queued means RUNNING with no heartbeat and no run id: a row another
        delivery claimed is left alone.
        """
        job_table = cls._job_table()
        with cls.session_scope() as session:
            result = session.execute(
                update(job_table)
                .where(
                    job_table.job_id == job_id,
                    job_table.status == "RUNNING",
                    job_table.heartbeat_at.is_(None),
                    job_table.run_id.is_(None),
                )
                .values(status="FAILED")
            )
            return result.rowcount == 1

    @classmethod
    def refresh_heartbeat(cls, job_id, run_id) -> bool:
        """Set the heartbeat of the job's row to now(), if run_id still holds it.

        Only a RUNNING row that carries ``run_id``: a re-queued or reset row
        (no run id), or one a newer run claimed, belongs to someone else, and a
        thread of an older run that is still alive never keeps it alive.

        Returns:
            Whether the heartbeat was written; False means the run was overtaken.
        """
        job_table = cls._job_table()
        with cls.session_scope() as session:
            result = session.execute(
                update(job_table)
                .where(
                    job_table.job_id == job_id,
                    job_table.status == "RUNNING",
                    job_table.run_id == run_id,
                )
                .values(heartbeat_at=func.now())
            )
            return result.rowcount == 1

    @classmethod
    def end_run(cls, job_id, run_id, status) -> bool:
        """Write a run's final status, if run_id still holds the RUNNING row.

        Returns:
            Whether the status was written; False means the run was overtaken
            (cancelled, swept, reset or replaced by a newer run) and wrote nothing.
        """
        job_table = cls._job_table()
        with cls.session_scope() as session:
            result = session.execute(
                update(job_table)
                .where(
                    job_table.job_id == job_id,
                    job_table.status == "RUNNING",
                    job_table.run_id == run_id,
                )
                .values(status=status)
            )
            return result.rowcount == 1

    @classmethod
    def fail_runs_without_heartbeat_since(cls, threshold):
        """Write FAILED to every RUNNING row whose heartbeat is older than threshold.

        One update; a queued row (no heartbeat) is never touched.

        Returns:
            ``(job_id, heartbeat_at)`` of every row it failed.
        """
        job_table = cls._job_table()
        with cls.session_scope() as session:
            result = session.execute(
                update(job_table)
                .where(
                    job_table.status == "RUNNING",
                    job_table.heartbeat_at < func.now() - threshold,
                )
                .values(status="FAILED")
                .returning(job_table.job_id, job_table.heartbeat_at)
            )
            return [(row.job_id, row.heartbeat_at) for row in result]

    @classmethod
    def get_job_columns(cls, job_id):
        """Retrieve all columns of a specific job entry based on its job ID."""
        log.debug(f"Get columns for job: {job_id}")

        job_table = cls._job_table()
        with cls.session_scope() as session:
            job_row = session.query(job_table).filter_by(job_id=job_id).first()

            if job_row is None:
                raise JobNotFound(job_id)

            job_columns = {
                column.name: getattr(job_row, column.name)
                for column in job_table.__table__.columns
            }

        return job_columns

    @classmethod
    def delete_job(cls, job_id) -> bool:
        """Delete a job's row unless it is RUNNING; return whether it was deleted.

        One conditional delete: a row under a live run (queued or claimed) stays,
        whatever the caller checked before (ADR 0005).

        Raises:
            JobNotFound: If the job has no row.
        """
        log.debug(f"Delete job: {job_id}")
        job_table = cls._job_table()
        with cls.session_scope() as session:
            result = session.execute(
                delete(job_table).where(
                    job_table.job_id == job_id,
                    job_table.status.is_distinct_from("RUNNING"),
                )
            )
            deleted = result.rowcount == 1
        if not deleted:
            cls._raise_if_no_row(job_id)
        return deleted

    @classmethod
    def list_job_ids(cls):
        """Return the ids of all jobs in the database."""
        job_table = cls._job_table()
        with cls.session_scope() as session:
            return {row.job_id for row in session.query(job_table.job_id)}

    @classmethod
    def list_jobs(cls):
        """List all jobs in the database with their submission date and status."""
        log.debug("List all jobs.")

        job_table = cls._job_table()
        with cls.session_scope() as session:
            job_rows = session.query(job_table).all()

            job_info = {}
            for job_row in job_rows:
                job_info[job_row.job_id] = {
                    column.name: getattr(job_row, column.name)
                    for column in job_table.__table__.columns
                }
        return job_info


class JobColumns:
    """The columns every app's ``jobs`` table carries.

    Not mapped and not a table: an app declares its own concrete class from
    this mixin, on the framework ``Base``, alongside whatever extra columns its
    own ``jobs`` table has::

        class JobTable(JobColumns, Base):
            __tablename__ = "jobs"

            input_data = Column(JSON)
            logs = Column(String)

        DbManager.job_table = JobTable

    The intersection, measured across COSMOPOLITAN, COSMONAUT and the reference
    domain on 2026-08-21: COSMONAUT has neither ``input_data`` nor ``logs``, so
    those two stay app-side rather than in this mixin. ``heartbeat_at`` is not
    measured but required: the framework's job run writes it (ADR 0004), so every
    app's table has to grow it before the app deploys this mapping. The same holds
    for ``run_id`` (ADR 0005). See
    docs/conventions/database_schema.md.
    """

    job_id = Column(String, primary_key=True)
    start_date = Column(Date)
    submitted = Column(Boolean)
    notified_end = Column(Boolean)
    status = Column(String)
    version = Column(String)
    # The job run's sign of life, always the database's now(); NULL while the
    # run is queued and no worker has claimed it (cosmo_ecosystem.job_run).
    heartbeat_at = Column(DateTime(timezone=True))
    # The identity of the job run that holds the row: a fresh UUID written by the
    # claim, NULL while queued or reset. The run's heartbeat and final status are
    # written only while the row still carries it (ADR 0005).
    run_id = Column(UUID(as_uuid=True))


class LogTable(Base):
    """SQLAlchemy model for the logs table."""

    __tablename__ = "logs"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime(timezone=False), nullable=False)
    pid = Column(Integer, nullable=False)
    level = Column(String(10), nullable=False)
    module = Column(String(50), nullable=False)
    message = Column(Text, nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        """Convert log record to dictionary format."""
        return {
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "pid": self.pid,
            "level": self.level,
            "message": self.message,
            "module": self.module,
        }


class JobLogTable(Base):
    """SQLAlchemy model for the job_logs table: one row per job log record.

    Separate from ``logs`` so the log purge does not cut a job log short and
    worker noise stays out. Written by ``job_log.JobLogHandler``, read and
    cleared through ``job_log``. ``id`` orders the records of one job.
    """

    __tablename__ = "job_logs"

    id = Column(BigInteger, primary_key=True)
    job_id = Column(String, nullable=False, index=True)
    timestamp = Column(DateTime(timezone=False), nullable=False)
    level = Column(String(10), nullable=False)
    module = Column(String, nullable=False)
    message = Column(Text, nullable=False)


if __name__ == "__main__":
    DbManager.check_existence("test_job")
