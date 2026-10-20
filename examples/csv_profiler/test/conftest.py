"""Setup tests with conditional fixture loading."""

import hashlib
import logging
import os
import pathlib
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import urllib.request

import pytest
import redis
from playwright.sync_api import ConsoleMessage
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from slugify import slugify
from sqlalchemy.exc import OperationalError

from cosmo_ecosystem.config import (
    OBJECT_STORAGE_SECRET_KEY,
    PORT,
    POSTGRES_PASSWORD,
    REDIS_DB,
    REDIS_HOST,
    REDIS_PASSWORD,
    REDIS_PORT,
)
from cosmo_ecosystem.db_manager import DbManager
from cosmo_ecosystem.object_storage_manager import (
    ObjectStorageError,
    create_bucket,
    setup_remote,
)

from csv_profiler.db_manager import JobTable

# Every test module in this suite imports DbManager directly (test_db_manager.py)
# or transitively through cosmo_ecosystem.job (test_e2e.py's dash_app fixture), so
# this has to be set once here, before collection, same as the seams in app.py.
DbManager.job_table = JobTable


def create_logger():
    """Create a logger with debug level."""
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logging.getLogger("urllib3").setLevel(logging.ERROR)
    logging.getLogger("requests").setLevel(logging.ERROR)
    return logger


log = create_logger()

_worker_log_path: pathlib.Path | None = None


def pytest_addoption(parser):
    """Add custom command-line options to pytest.

    Registers the --no-services flag which controls whether service-dependent
    fixtures (dash_app, celery_worker) are loaded.
    """
    parser.addoption(
        "--no-services",
        action="store_true",
        default=False,
        help="Skip service-dependent fixtures (assumes services not available)",
    )


def pytest_configure(config):
    """Perform early configuration and service health checks.

    Runs once at the start of the test session, before any tests.
    If --no-services is NOT set, we verify all service connectivity.
    """
    skip_services = config.getoption("--no-services")

    if skip_services:
        logging.info("Skipping service health checks (--no-services flag set)")
        return

    # Give services a moment to fully initialize after health checks
    time.sleep(4)

    # Check rclone availability and object storage connectivity
    try:
        subprocess.run(
            ["rclone", "--version"], check=True, text=True, capture_output=True
        )
    except FileNotFoundError:
        pytest.exit("rclone command not available")

    try:
        setup_remote()
        create_bucket()
        logging.info("rclone object storage connectivity check passed")
    except ObjectStorageError as e:
        pytest.exit(f"Object storage (S3) connectivity check failed: {e}")

    # Validate credentials are test values
    if POSTGRES_PASSWORD != "test" or OBJECT_STORAGE_SECRET_KEY != "secretkey":
        pytest.exit("Environment variables not set to test values")

    # Check PostgreSQL connectivity
    try:
        DbManager.check_existence("test")
        logging.info("Database connection successful")
    except OperationalError as e:
        logging.error(f"Database connection failed: {e}")
        pytest.exit(f"PostgreSQL not available: {e}")

    # Check Redis connectivity
    try:
        redis_port = REDIS_PORT
        if redis_port and str(redis_port).startswith("tcp://"):
            redis_port = redis_port.split(":")[-1]

        redis_client = redis.Redis(
            host=REDIS_HOST,
            port=int(redis_port),
            db=int(REDIS_DB),
            password=REDIS_PASSWORD if REDIS_PASSWORD else None,
            socket_connect_timeout=5,
        )
        redis_client.ping()
        logging.info("Redis connection successful")
    except (redis.ConnectionError, redis.TimeoutError) as e:
        logging.error(f"Redis connection failed: {e}")
        pytest.exit(f"Redis not available: {e}")


@pytest.fixture
def logger():
    """Create a logger with suppressed external sources."""
    return create_logger()


def _truncate_file_name(file_name: str) -> str:
    if len(file_name) < 256:
        return file_name
    hash_part = hashlib.sha256(file_name.encode()).hexdigest()[:7]
    return f"{file_name[:100]}-{hash_part}-{file_name[-100:]}"


class _LogCollector(logging.Handler):
    """Handler that collects formatted log records in memory."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[str] = []
        self.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(self.format(record))


@pytest.fixture
def page(
    page: Page, request: pytest.FixtureRequest, pytestconfig: pytest.Config
) -> Page:
    """Wrap pytest-playwright's page fixture to capture artifacts on failure."""
    console_messages: list[str] = []

    def _on_console(msg: ConsoleMessage) -> None:
        console_messages.append(f"[{msg.type}] {msg.text}")

    page.on("console", _on_console)

    log_collector = _LogCollector()
    root_logger = logging.getLogger()
    root_logger.addHandler(log_collector)

    yield page

    root_logger.removeHandler(log_collector)

    failed = request.node.rep_call.failed if hasattr(request.node, "rep_call") else True
    if not failed:
        return

    output_dir = pathlib.Path(pytestconfig.getoption("--output")).absolute()
    test_dir = output_dir / _truncate_file_name(slugify(request.node.nodeid))
    test_dir.mkdir(parents=True, exist_ok=True)

    try:
        html_content = page.content()
        (test_dir / "page.html").write_text(html_content, encoding="utf-8")
    except PlaywrightError:
        pass  # Page may have already closed

    if console_messages:
        (test_dir / "console.log").write_text(
            "\n".join(console_messages), encoding="utf-8"
        )

    if log_collector.records:
        (test_dir / "server.log").write_text(
            "\n".join(log_collector.records), encoding="utf-8"
        )

    if _worker_log_path and _worker_log_path.stat().st_size > 0:
        shutil.copy2(_worker_log_path, test_dir / "worker.log")


@pytest.fixture(scope="session")
def worker_log_path():
    """Expose the worker log file path for assertions in tests."""
    return _worker_log_path


@pytest.fixture(scope="session")
def dash_app(request):
    """Start the Dash app in a background thread with graceful shutdown.

    Uses werkzeug.serving.make_server() directly to retain a server handle
    for clean shutdown, preventing 'Address already in use' errors.

    This fixture is skipped if --no-services flag is set.
    """
    from werkzeug.serving import make_server

    skip_services = request.config.getoption("--no-services")
    if skip_services:
        pytest.skip("Skipping dash_app fixture (--no-services flag set)")

    from csv_profiler.app import app

    port = int(PORT)
    srv = make_server("localhost", port, app.server)
    thread = threading.Thread(target=srv.serve_forever)
    thread.start()

    # Poll until the server responds instead of a blind sleep
    url = f"http://localhost:{port}/"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            break
        except OSError:
            time.sleep(0.2)
    else:
        pytest.exit("Dash app failed to start within 10 seconds")

    log.info("Dash app started on port %s", port)

    yield app

    # Graceful shutdown: stop accepting requests, then join thread
    log.info("Shutting down Dash app...")
    srv.shutdown()
    thread.join(timeout=10)
    log.info("Dash app shut down")


@pytest.fixture(scope="session")
def celery_worker(request):
    """Start a Celery worker for testing job processing.

    Spawns a Celery worker subprocess that:
    - Listens to computation, maintenance, and celery queues
    - Uses concurrency=1 for deterministic testing
    - Uses prefork pool for proper task termination
    - Enables task events for inspect() API functionality

    This fixture is skipped if --no-services flag is set.
    """
    skip_services = request.config.getoption("--no-services")
    if skip_services:
        pytest.skip("Skipping celery_worker fixture (--no-services flag set)")

    global _worker_log_path  # noqa: PLW0603

    log.info("Starting Celery worker for testing...")

    # Redirect worker output to a temp file so it can be captured as a test artifact
    worker_log_file = tempfile.NamedTemporaryFile(
        mode="w", prefix="worker_", suffix=".log", delete=False
    )
    _worker_log_path = pathlib.Path(worker_log_file.name)

    worker_env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    worker_process = subprocess.Popen(
        [
            "uv",
            "run",
            "celery",
            "-A",
            "csv_profiler.celery_app.celery",
            "worker",
            "--loglevel=debug",
            "--concurrency=1",
            "--pool=prefork",
            "--queues=computation,maintenance,celery",
            "--hostname=worker@test",
            "-E",
        ],
        stdout=worker_log_file,
        stderr=worker_log_file,
        text=True,
        env=worker_env,
        preexec_fn=os.setsid,
    )

    # Give worker time to start and connect to broker
    time.sleep(3)

    # Check if worker process is still running (not crashed)
    if worker_process.poll() is not None:
        worker_log_file.close()
        stderr = _worker_log_path.read_text()
        pytest.exit(f"Celery worker failed to start. stderr: {stderr}")

    log.info("Celery worker started successfully")

    yield worker_process

    # Close the log file so all output is flushed
    worker_log_file.close()

    # Cleanup: terminate worker process and all child processes
    log.info("Terminating Celery worker...")
    try:
        os.killpg(os.getpgid(worker_process.pid), signal.SIGTERM)
        try:
            worker_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(worker_process.pid), signal.SIGKILL)
            worker_process.wait()
        log.info("Celery worker terminated")
    except ProcessLookupError:
        pass
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning(f"Error during worker cleanup: {e}")
        try:
            os.killpg(os.getpgid(worker_process.pid), signal.SIGKILL)
        except (ProcessLookupError, OSError):
            pass
