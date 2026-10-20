"""Logging configuration for Cosmo Ecosystem applications.

Every builder takes ``excluded_packages``: the noisy libraries only the calling
app pulls in. They are added to DEFAULT_EXCLUDED_PACKAGES, so an app never has
to restate the framework's own exclusions — and never has to subclass the filter
to extend it.
"""

import datetime
import logging
import time

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
postgres_params = {
    "dbname": POSTGRES_DB,
    "user": POSTGRES_USER,
    "password": POSTGRES_PASSWORD,
    "host": POSTGRES_HOST_NAME,
    "port": POSTGRES_PORT,
}


class PostgreSQLHandler(logging.Handler):
    """A log handler that writes log records to a PostgreSQL database."""

    def __init__(self, connection_params):
        """Initialize the handler with PostgreSQL connection parameters.

        Args:
            connection_params (dict): Connection parameters for PostgreSQL
                                     (dbname, user, password, host, port)
        """
        super().__init__()
        self.connection_params = connection_params
        # Create a connection pool for better performance
        # Add keepalive settings to prevent connections from going stale
        pool_params = {
            **connection_params,
            "keepalives": 1,
            "keepalives_idle": 30,  # Start keepalive after 30s idle
            "keepalives_interval": 10,  # Send keepalive every 10s
            "keepalives_count": 5,  # 5 failed keepalives = dead connection
        }
        max_retries = 5
        retry_delay_seconds = 2
        for attempt in range(1, max_retries + 1):
            try:
                self.connection_pool = pool.SimpleConnectionPool(
                    1,
                    10,  # min and max connections
                    **pool_params,
                )
                break
            except psycopg2.OperationalError:
                if attempt == max_retries:
                    raise
                print(
                    f"PostgreSQL not ready, retrying in {retry_delay_seconds}s "
                    f"(attempt {attempt}/{max_retries})"
                )
                time.sleep(retry_delay_seconds)

    def emit(self, record):
        """Write the log record to the database.

        Args:
            record: The log record to write.
        """
        # Get a connection from the pool
        connection = self.connection_pool.getconn()
        connection_is_bad = False

        try:
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
        except psycopg2.OperationalError as e:
            # Connection is bad (timeout, network issue, etc.)
            # Mark it as bad so it's not returned to the pool
            connection_is_bad = True
            print(f"Database connection error (will retry with new connection): {e}")

            # Try once more with a fresh connection
            try:
                new_connection = self.connection_pool.getconn()
                try:
                    with new_connection.cursor() as cursor:
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
                        new_connection.commit()
                finally:
                    self.connection_pool.putconn(new_connection)
            except (
                Exception
            ) as retry_error:  # retry can fail for any DB reason; fatal  # noqa
                print(
                    f"FATAL: Database logging failed after retry. "
                    f"Worker cannot continue without logging capability: {retry_error}"
                )
                # Re-raise to fail the worker - logging is critical
                raise
        except (
            Exception
        ) as e:  # any DB error is fatal — worker cannot operate without logging
            # Any other database error is also fatal
            print(f"FATAL: Error writing to PostgreSQL: {e}")
            # Re-raise to fail the worker
            raise
        finally:
            # Return the connection to the pool, or close it if it's bad
            if connection_is_bad:
                try:
                    connection.close()
                except (
                    Exception
                ):  # close can fail on broken connection; safe to ignore  # noqa
                    pass
                # putconn with close=True tells the pool this connection is bad
                self.connection_pool.putconn(connection, close=True)
            else:
                self.connection_pool.putconn(connection)

    def close(self):
        """Close all database connections when the handler is closed."""
        if hasattr(self, "connection_pool") and self.connection_pool:
            self.connection_pool.closeall()
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

    Args:
        log_file_path: Path of the job's log file.
        excluded_packages: Extra packages to mute — see ExcludeSubmodulesFilter.
    """
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
