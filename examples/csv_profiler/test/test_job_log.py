"""Test the framework's job log against a real Postgres server."""

import datetime
import logging
import re
import time

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cosmo_ecosystem import job_log
from cosmo_ecosystem.db_manager import DbManager
from cosmo_ecosystem.job_log import JobLogHandler
from cosmo_ecosystem.job_persistence import delete_job, delete_jobs, save

# One record as read() formats it: [asctime] LEVEL in module: message
LINE = re.compile(r"^\[\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3}\] (\w+) in (\w+): (.*)$")


def _logger(name):
    """Return a DEBUG logger that does not propagate to the suite's handlers."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger


def _attached(logger, job_id, excluded_packages=()):
    """Attach a fresh JobLogHandler for job_id to logger and return it."""
    handler = JobLogHandler(job_id, excluded_packages=excluded_packages)
    logger.addHandler(handler)
    return handler


def _detach(logger, handler):
    """Remove handler from logger and close it."""
    logger.removeHandler(handler)
    handler.close()


def _read_until(job_id, text, timeout):
    """Poll read(job_id) until it contains text or timeout seconds pass."""
    deadline = time.monotonic() + timeout
    content = job_log.read(job_id)
    while text not in content and time.monotonic() < deadline:
        time.sleep(0.1)
        content = job_log.read(job_id)
    return content


def test_records_are_readable_from_another_connection_while_the_handler_is_open():
    """A running job's log can be watched from any pod, before the run ends."""
    job_id = "test_job_log_live"
    logger = _logger("test_job_log.live")
    handler = _attached(logger, job_id)

    try:
        logger.info("first step done")
        logger.debug("detail of the second step")

        content = _read_until(job_id, "detail of the second step", timeout=5)

        lines = content.splitlines()
        assert [LINE.match(line).groups() for line in lines] == [
            ("INFO", "test_job_log", "first step done"),
            ("DEBUG", "test_job_log", "detail of the second step"),
        ]
    finally:
        _detach(logger, handler)
        job_log.clear(job_id)


def _log_and_close(job_id, *messages):
    """Write messages to job_id's job log through a handler that is then closed."""
    logger = _logger(f"test_job_log.{job_id}")
    handler = _attached(logger, job_id)
    for message in messages:
        logger.info(message)
    _detach(logger, handler)


def _row():
    """Return a complete job row."""
    return {
        "start_date": datetime.date.today(),
        "input_data": {},
        "submitted": False,
        "notified_end": False,
        "logs": "",
        "status": "COMPLETED",
        "version": "0.1.0",
    }


def test_deleting_a_job_deletes_its_job_log():
    """A job log does not outlive its job."""
    job_id = "test_job_log_delete_job"
    save(job_id, _row())
    _log_and_close(job_id, "computed")

    delete_job(job_id)

    assert job_log.read(job_id) == ""


def test_deleting_several_jobs_deletes_their_job_logs():
    """The dashboard's multi-row delete takes the job logs along too."""
    job_ids = ["test_job_log_delete_jobs_a", "test_job_log_delete_jobs_b"]
    for job_id in job_ids:
        save(job_id, _row())
        _log_and_close(job_id, "computed")

    delete_jobs(job_ids)

    assert [job_log.read(job_id) for job_id in job_ids] == ["", ""]


def test_the_job_log_of_an_unknown_job_is_empty():
    """A job that never ran has nothing to show, and that is not an error."""
    assert job_log.read("test_job_log_never_ran") == ""


def test_clearing_a_job_log_leaves_other_jobs_alone():
    """Resetting one job must not wipe another job's log."""
    cleared, kept = "test_job_log_clear_a", "test_job_log_clear_b"
    _log_and_close(cleared, "a computed")
    _log_and_close(kept, "b computed")

    try:
        job_log.clear(cleared)

        assert job_log.read(cleared) == ""
        assert job_log.read(kept).endswith("INFO in test_job_log: b computed\n")
    finally:
        job_log.clear(kept)


def test_records_from_excluded_packages_stay_out_of_the_job_log():
    """Noisy libraries' DEBUG output does not bury the computation's own lines."""
    job_id = "test_job_log_excluded"
    handler = JobLogHandler(job_id, excluded_packages=("noisy_app_lib",))
    loggers = [
        _logger("noisy_app_lib.render"),  # the app's own exclusion
        _logger("botocore.auth"),  # in DEFAULT_EXCLUDED_PACKAGES
        _logger("test_job_log.excluded"),
    ]
    for logger in loggers:
        logger.addHandler(handler)

    try:
        for logger in loggers:
            logger.debug(f"from {logger.name}")
        for logger in loggers:
            logger.removeHandler(handler)
        handler.close()

        assert [
            LINE.match(line).group(3) for line in job_log.read(job_id).splitlines()
        ] == ["from test_job_log.excluded"]
    finally:
        job_log.clear(job_id)


def test_an_unreachable_database_raises_nothing_and_warns_in_the_worker_log(
    monkeypatch, caplog
):
    """A logging failure must not abort an hour-long computation."""
    unreachable = create_engine("postgresql+psycopg2://nobody:none@127.0.0.1:1/none")
    monkeypatch.setattr(DbManager, "_Session", sessionmaker(bind=unreachable))
    logger = _logger("test_job_log.unreachable")
    handler = _attached(logger, "test_job_log_unreachable")

    with caplog.at_level(logging.WARNING, logger="cosmo_ecosystem.job_log"):
        logger.info("computed")
        _detach(logger, handler)

    assert [
        record.levelname
        for record in caplog.records
        if "test_job_log_unreachable" in record.getMessage()
    ] == ["WARNING"]


def test_closing_a_handler_twice_raises_nothing():
    """logging.shutdown closes every live handler again at interpreter exit."""
    job_id = "test_job_log_close_twice"
    handler = JobLogHandler(job_id)

    try:
        handler.close()
        handler.close()
    finally:
        job_log.clear(job_id)
