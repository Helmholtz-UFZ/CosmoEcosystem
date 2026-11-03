"""Logging configuration for Cosmo Ecosystem applications.

Every builder takes ``excluded_packages``: the noisy libraries only the calling
app pulls in. They are added to DEFAULT_EXCLUDED_PACKAGES, so an app never has
to restate the framework's own exclusions — and never has to subclass the filter
to extend it.
"""

import datetime
import logging
import os
import time
import warnings

import psycopg2
from psycopg2 import pool

from cosmo_ecosystem.config import (
    POSTGRES_DB,
    POSTGRES_HOST_NAME,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)

format_string = (
    "[%(asctime)s] [PID:%(process)d] %(levelname)s in %(module)s: %(message)s"
)
# Pools a forked child inherited from its parent. The parent still owns their
# sockets: letting the last reference go would garbage-collect the connections,
# and closing a psycopg2 connection sends the server a Terminate for the
# session the parent is using. They are kept alive, never closed.
_INHERITED_POOLS = []

postgres_params = {
    "dbname": POSTGRES_DB,
    "user": POSTGRES_USER,
    "password": POSTGRES_PASSWORD,
    "host": POSTGRES_HOST_NAME,
    "port": POSTGRES_PORT,
}


POOL_CONNECT_TIMEOUT_SECONDS = 5
# After a failed pool build the handler drops records for this long without
# touching the network: each attempt runs under the handler lock, so every
# log call in the process would wait for it.
POOL_RETRY_COOLDOWN_SECONDS = 30


class PoolUnavailable(psycopg2.OperationalError):
    """The pool could not be built a moment ago; records are dropped meanwhile."""


class PostgreSQLHandler(logging.Handler):
    """A log handler that writes log records to a PostgreSQL database."""

    def __init__(self, connection_params, clock=time.monotonic):
        """Initialize the handler with PostgreSQL connection parameters.

        Args:
            connection_params (dict): Connection parameters for PostgreSQL
                                     (dbname, user, password, host, port)
            clock: Monotonic clock for the retry cooldown; tests pass their own.
        """
        super().__init__()
        self.connection_params = connection_params
        # No connection here: dictConfig builds this handler at import, and a
        # preloading gunicorn master would hand its socket to every forked
        # worker. The pool is built on first use, once per process.
        self._connection_pool = None
        self._pool_pid = None
        self._clock = clock
        self._build_failed_at = None

    @property
    def connection_pool(self):
        """The pool of the current process, built on first use.

        After a fork the inherited pool shares its sockets with the parent, so a
        process whose pid differs from the creator's builds its own and parks the
        inherited one in ``_INHERITED_POOLS``, neither closed nor collected.

        Raises:
            psycopg2.OperationalError: If PostgreSQL cannot be reached. One
                attempt, then ``PoolUnavailable`` until the cooldown is over.
        """
        # The handler's own lock, an RLock that logging re-creates in a forked
        # child: a lock of ours held by another thread at fork time would stay
        # locked there for good. emit already holds it, hence re-entrant.
        self.acquire()
        try:
            if self._connection_pool is None or self._pool_pid != os.getpid():
                if self._connection_pool is not None:
                    _INHERITED_POOLS.append(self._connection_pool)
                    self._connection_pool = None
                self._build_pool()
                self._pool_pid = os.getpid()
            return self._connection_pool
        finally:
            self.release()

    def _build_pool(self):
        """Build the pool, or fail fast while the last build's cooldown runs."""
        if (
            self._build_failed_at is not None
            and self._clock() - self._build_failed_at < POOL_RETRY_COOLDOWN_SECONDS
        ):
            raise PoolUnavailable(
                f"PostgreSQL unreachable, next attempt {POOL_RETRY_COOLDOWN_SECONDS}s "
                "after the last failure; log record dropped"
            )
        try:
            self._connection_pool = self._connect()
        except psycopg2.OperationalError:
            self._build_failed_at = self._clock()
            raise
        self._build_failed_at = None

    def _connect(self):
        """Open a connection pool: a single attempt."""
        # Add keepalive settings to prevent connections from going stale
        pool_params = {
            **self.connection_params,
            # Without it a connect to a dead host waits for the OS TCP timeout.
            "connect_timeout": POOL_CONNECT_TIMEOUT_SECONDS,
            "keepalives": 1,
            "keepalives_idle": 30,  # Start keepalive after 30s idle
            "keepalives_interval": 10,  # Send keepalive every 10s
            "keepalives_count": 5,  # 5 failed keepalives = dead connection
        }
        # No retry loop here: this runs inside emit, under the handler lock, and
        # every log call in the process waits for it. A failed attempt goes to
        # handleError and the next record tries again.
        return pool.SimpleConnectionPool(
            1,
            10,  # min and max connections
            **pool_params,
        )

    def emit(self, record):
        """Write the log record to the database.

        A failure never raises into the code that logged: it goes to
        ``handleError``, as the standard library's handlers do.

        Args:
            record: The log record to write.
        """
        try:
            self._write(record)
        except Exception:  # noqa: BLE001
            # Any failure (pool build, getconn, execute) must stay out of the
            # caller's log.*() call, whatever its type: the stdlib's own
            # handlers catch exactly this much.
            self.handleError(record)

    def _write(self, record):
        """Insert the record, once more on a fresh connection if one was bad."""
        connection_pool = self.connection_pool
        for attempt in (1, 2):
            connection = connection_pool.getconn()
            connection_is_bad = False
            try:
                self._insert(connection, record)
                return
            except psycopg2.OperationalError as e:
                # Timeout, network issue, ...: the pool must not keep it.
                connection_is_bad = True
                if attempt == 2:
                    raise
                print(
                    f"Database connection error (will retry with new connection): {e}"
                )
            finally:
                connection_pool.putconn(connection, close=connection_is_bad)

    def _insert(self, connection, record):
        """Write one record on ``connection`` and commit."""
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO logs
                (timestamp, pid, level, module, message)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    datetime.datetime.fromtimestamp(record.created),
                    record.process,
                    record.levelname,
                    record.module,
                    self.format(record),
                ),
            )
            connection.commit()

    def close(self):
        """Close all database connections when the handler is closed."""
        # A pool inherited from a parent process is not ours to close.
        if self._connection_pool is not None and self._pool_pid == os.getpid():
            self._connection_pool.closeall()
        super().close()


# Packages every consumer inherits: framework-level noise, nothing domain-specific.
# boto3/botocore/s3transfer arrive with object_storage_manager's presigning. At
# DEBUG botocore writes ~60 records per signed URL, one of them the signature —
# enough to rebuild a working download link from the logs page.
DEFAULT_EXCLUDED_PACKAGES = ("watchdog", "selenium", "boto3", "botocore", "s3transfer")
EXCLUDED_MODULES = ("_internal",)


class ExcludeSubmodulesFilter(logging.Filter):
    """Drop records from noisy third-party packages."""

    def __init__(self, excluded_packages=()):
        """Initialize the filter.

        Args:
            excluded_packages: Packages to mute *in addition to*
                DEFAULT_EXCLUDED_PACKAGES. An app passes the libraries only it
                pulls in (matplotlib, rasterio, …), whose DEBUG output would
                otherwise fill the logs table.
        """
        super().__init__()
        self.excluded_packages = (*DEFAULT_EXCLUDED_PACKAGES, *excluded_packages)

    def filter(self, record):
        """Return False for records from an excluded package or module."""
        return (
            not record.name.startswith(self.excluded_packages)
            and record.module not in EXCLUDED_MODULES
        )


def _filter_config(excluded_packages):
    """Build the dictConfig ``filters`` block, wiring in the extra packages."""
    return {
        "exclude_submodules": {
            "()": ExcludeSubmodulesFilter,
            "excluded_packages": list(excluded_packages),
        }
    }


def get_logger_config_computation(log_file_path, excluded_packages=()):
    """Get the config dic for the computation logger.

    Deprecated: a job's log lives in the ``job_logs`` table now, and
    ``job_run.run`` captures it. Swapping the logging config inside a task
    replaces the worker's handlers, the ``JobLogHandler`` among them. Will be
    removed in the next version.

    Args:
        log_file_path: Path of the job's log file.
        excluded_packages: Extra packages to mute — see ExcludeSubmodulesFilter.
    """
    warnings.warn(
        "get_logger_config_computation() is deprecated and will be removed: "
        "a computation task calls cosmo_ecosystem.job_run.run, which writes "
        "the job log to the job_logs table.",
        DeprecationWarning,
        stacklevel=2,
    )
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": _filter_config(excluded_packages),
        "handlers": {
            "file": {
                "class": "logging.FileHandler",
                "level": "DEBUG",
                "formatter": "detailed",
                "filename": log_file_path,
                "mode": "w",
                "filters": ["exclude_submodules"],
            },
        },
        "formatters": {
            "detailed": {
                "format": "[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
            },
        },
        "root": {
            "level": "DEBUG",
            "handlers": ["file"],
            "filters": ["exclude_submodules"],
        },
    }


def _build_stream_config(stream, disable_existing_loggers, excluded_packages):
    """Build a logging config that writes to a stream and PostgreSQL.

    Args:
        stream: The stream ext:// URI for the StreamHandler
            (e.g. "ext://sys.stderr" or "ext://sys.__stderr__")
        disable_existing_loggers: Whether to disable loggers not in the config.
            False preserves Celery's own handlers; True is the default for the
            web process in production.
        excluded_packages: Extra packages to mute — see ExcludeSubmodulesFilter.

    Returns:
        dict: Logging configuration dictionary for use with dictConfig()
    """
    return {
        "version": 1,
        "disable_existing_loggers": disable_existing_loggers,
        "formatters": {
            "default": {"format": format_string},
            "message_only": {"format": "%(message)s"},
        },
        "filters": _filter_config(excluded_packages),
        "handlers": {
            "stream": {
                "class": "logging.StreamHandler",
                "stream": stream,
                "formatter": "default",
                "filters": ["exclude_submodules"],
                "level": "DEBUG",
            },
            "postgres": {
                "class": __name__ + ".PostgreSQLHandler",
                "level": "DEBUG",
                "formatter": "message_only",
                "filters": ["exclude_submodules"],
                "connection_params": postgres_params,
            },
        },
        "root": {
            "handlers": ["stream", "postgres"],
            "level": "DEBUG",
            "filters": ["exclude_submodules"],
        },
    }


def get_logger_config_web(debug, excluded_packages=()):
    """Get the logging configuration for the web process (Dash/Flask).

    Writes to sys.stderr and PostgreSQL.

    Args:
        debug (bool): Whether to enable debug mode logging
        excluded_packages: Extra packages to mute — see ExcludeSubmodulesFilter.

    Returns:
        dict: Logging configuration dictionary for use with dictConfig()
    """
    return _build_stream_config(
        stream="ext://sys.stderr",
        disable_existing_loggers=False,
        excluded_packages=excluded_packages,
    )


def get_logger_config_worker(excluded_packages=()):
    """Get the logging configuration for use inside a Celery worker task.

    Writes to sys.__stderr__ (the real stderr fd) instead of sys.stderr.
    This is necessary because Celery's prefork pool replaces sys.stderr
    with a LoggingProxy, and writing to it from a StreamHandler causes
    circular recursion.

    disable_existing_loggers is always False to preserve Celery's own
    logging handlers.

    Args:
        excluded_packages: Extra packages to mute — see ExcludeSubmodulesFilter.

    Returns:
        dict: Logging configuration dictionary for use with dictConfig()
    """
    return _build_stream_config(
        stream="ext://sys.__stderr__",
        disable_existing_loggers=False,
        excluded_packages=excluded_packages,
    )
