"""The logging configuration builders apps call at startup."""

import gc
import logging
import threading
import time
import weakref

import psycopg2
import pytest

from cosmo_ecosystem import logger as logger_module
from cosmo_ecosystem.logger import get_logger_config_computation


def test_the_computation_logger_config_warns_that_it_will_go(tmp_path):
    """Apps get one version's notice before the per-job log file config is removed."""
    with pytest.warns(DeprecationWarning, match="job_run.run"):
        config = get_logger_config_computation(str(tmp_path / "logs"))

    assert config["handlers"]["file"]["filename"] == str(tmp_path / "logs")


class _FakePool:
    """Stands in for SimpleConnectionPool: counts builds, hands out fake connections.

    ``fail_getconn`` and ``fail_execute`` are class-level switches a test sets to
    an exception to raise; ``put`` records every ``putconn`` as (connection, close).
    """

    built = []
    build_delay = 0
    fail_getconn = None
    fail_execute = None

    def __init__(self, minconn, maxconn, **params):
        time.sleep(_FakePool.build_delay)
        self.closed = False
        self.put = []
        _FakePool.built.append(self)

    def getconn(self):
        if _FakePool.fail_getconn is not None:
            raise _FakePool.fail_getconn
        return _FakeConnection()

    def putconn(self, connection, close=False):
        self.put.append((connection, close))

    def closeall(self):
        self.closed = True

    def __del__(self):
        # Garbage collection of a real pool closes its connections, which sends
        # a Terminate on a socket a parent process may still own.
        self.closed = True


class _FakeConnection:
    def cursor(self):
        return _FakeCursor()

    def commit(self):
        pass


class _FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        if _FakePool.fail_execute is not None:
            raise _FakePool.fail_execute


@pytest.fixture
def fake_pool(monkeypatch):
    _FakePool.built = []
    _FakePool.build_delay = 0
    _FakePool.fail_getconn = None
    _FakePool.fail_execute = None
    monkeypatch.setattr(logger_module.pool, "SimpleConnectionPool", _FakePool)
    monkeypatch.setattr(logger_module, "_INHERITED_POOLS", [])
    return _FakePool


def _record():
    return logging.LogRecord("t", logging.INFO, __file__, 1, "msg", None, None)


def test_the_postgres_handler_opens_no_connection_when_it_is_built(fake_pool):
    """dictConfig builds the handler at import; a preloading master must not connect."""
    logger_module.PostgreSQLHandler({})

    assert fake_pool.built == []


def test_the_postgres_handler_builds_its_pool_on_first_use_only(fake_pool):
    handler = logger_module.PostgreSQLHandler({})

    handler.emit(_record())
    handler.emit(_record())

    assert len(fake_pool.built) == 1


def test_a_forked_process_gets_its_own_pool_and_leaves_the_parents_open(
    fake_pool, monkeypatch
):
    """A gunicorn worker inherits the master's sockets; sharing them corrupts the stream."""
    handler = logger_module.PostgreSQLHandler({})
    handler.emit(_record())
    parent_pool = weakref.ref(fake_pool.built[0])
    fake_pool.built.clear()

    monkeypatch.setattr(logger_module.os, "getpid", lambda: -1)
    handler.emit(_record())
    handler.close()
    gc.collect()

    assert len(fake_pool.built) == 1
    assert parent_pool() is not None, "inherited pool was garbage collected"
    assert not parent_pool().closed


def test_two_threads_on_a_fresh_handler_build_one_pool(fake_pool):
    fake_pool.build_delay = 0.1
    handler = logger_module.PostgreSQLHandler({})
    threads = [
        threading.Thread(target=lambda: handler.connection_pool) for _ in range(4)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(fake_pool.built) == 1


class _Clock:
    """A clock the test moves by hand."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return _Clock()


@pytest.fixture
def handler_errors(fake_pool, monkeypatch, clock):
    """A handler whose ``handleError`` calls are collected instead of printed."""
    handler = logger_module.PostgreSQLHandler({}, clock=clock)
    errors = []
    monkeypatch.setattr(handler, "handleError", errors.append)
    return handler, errors


def test_an_unreachable_database_does_not_raise_into_the_log_call(
    monkeypatch, handler_errors
):
    def refuse(*args, **kwargs):
        raise psycopg2.OperationalError("connection refused")

    monkeypatch.setattr(logger_module.pool, "SimpleConnectionPool", refuse)
    handler, errors = handler_errors
    log = logging.getLogger("test_unreachable")
    log.addHandler(handler)
    try:
        log.warning("database is down")
    finally:
        log.removeHandler(handler)

    assert len(errors) == 1


def _flaky_factory(monkeypatch, failures):
    """Patch the pool factory to raise ``failures`` times, then build; return the call log."""
    calls = []

    def factory(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) <= failures:
            raise psycopg2.OperationalError("starting up")
        return _FakePool(*args, **kwargs)

    monkeypatch.setattr(logger_module.pool, "SimpleConnectionPool", factory)
    return calls


def test_a_failed_pool_build_is_not_retried_within_the_cooldown(
    monkeypatch, handler_errors, clock
):
    """Every record would otherwise block on a connect attempt under the handler lock."""
    calls = _flaky_factory(monkeypatch, failures=1000)
    handler, errors = handler_errors

    for _ in range(5):
        clock.now += logger_module.POOL_RETRY_COOLDOWN_SECONDS / 10
        handler.emit(_record())

    assert len(calls) == 1
    assert len(errors) == 5  # every record is reported dropped


def test_a_failed_pool_build_is_retried_after_the_cooldown(
    monkeypatch, handler_errors, clock
):
    calls = _flaky_factory(monkeypatch, failures=1)
    handler, errors = handler_errors

    handler.emit(_record())
    clock.now += logger_module.POOL_RETRY_COOLDOWN_SECONDS + 1
    handler.emit(_record())
    handler.emit(_record())

    assert len(calls) == 2
    assert len(errors) == 1  # only the first record failed


def test_the_pool_connects_with_a_timeout(fake_pool, monkeypatch):
    """A connect to a dead host must not block the log call for the OS timeout."""
    params = []
    monkeypatch.setattr(
        logger_module.pool,
        "SimpleConnectionPool",
        lambda *args, **kwargs: params.append(kwargs) or _FakePool(*args, **kwargs),
    )

    logger_module.PostgreSQLHandler({"host": "db"}).emit(_record())

    assert params[0]["connect_timeout"] == 5
    assert params[0]["host"] == "db"


def test_a_failing_getconn_goes_to_handle_error(fake_pool, handler_errors):
    fake_pool.fail_getconn = logger_module.pool.PoolError("exhausted")
    handler, errors = handler_errors

    handler.emit(_record())

    assert len(errors) == 1


def test_a_bad_connection_is_closed_and_the_record_retried_once(
    fake_pool, handler_errors
):
    fake_pool.fail_execute = psycopg2.OperationalError("server closed")
    handler, errors = handler_errors

    handler.emit(_record())

    closes = [close for _, close in fake_pool.built[0].put]
    assert closes == [True, True]  # first attempt and the one retry, both dropped
    assert len(errors) == 1


def test_another_database_error_goes_to_handle_error_and_returns_the_connection(
    fake_pool, handler_errors
):
    fake_pool.fail_execute = psycopg2.ProgrammingError("no table logs")
    handler, errors = handler_errors

    handler.emit(_record())

    assert [close for _, close in fake_pool.built[0].put] == [False]
    assert len(errors) == 1
