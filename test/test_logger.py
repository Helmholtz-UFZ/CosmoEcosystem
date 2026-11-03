"""The logging configuration builders apps call at startup."""

import logging

import pytest

from cosmo_ecosystem import logger as logger_module
from cosmo_ecosystem.logger import get_logger_config_computation


def test_the_computation_logger_config_warns_that_it_will_go(tmp_path):
    """Apps get one version's notice before the per-job log file config is removed."""
    with pytest.warns(DeprecationWarning, match="job_run.run"):
        config = get_logger_config_computation(str(tmp_path / "logs"))

    assert config["handlers"]["file"]["filename"] == str(tmp_path / "logs")


class _FakePool:
    """Stands in for SimpleConnectionPool: counts builds, hands out a fake connection."""

    built = []

    def __init__(self, minconn, maxconn, **params):
        self.closed = False
        _FakePool.built.append(self)

    def getconn(self):
        return _FakeConnection()

    def putconn(self, connection, close=False):
        pass

    def closeall(self):
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
        pass


@pytest.fixture
def fake_pool(monkeypatch):
    _FakePool.built = []
    monkeypatch.setattr(logger_module.pool, "SimpleConnectionPool", _FakePool)
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
    parent_pool = fake_pool.built[0]

    monkeypatch.setattr(logger_module.os, "getpid", lambda: -1)
    handler.emit(_record())
    handler.close()

    assert len(fake_pool.built) == 2
    assert not parent_pool.closed
