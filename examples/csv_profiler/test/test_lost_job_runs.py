"""Lost job runs end FAILED, and a redelivery never restarts one (ADR 0004).

Each test starts its own Celery worker (prefork, ``--concurrency=1``) from the
test domain ``lost_run_domain``, whose slow task gives the test a job run in
flight, and kills it the two ways production does:

- the prefork child alone (cgroup OOM, hard time limit, admin kill): the worker
  acks the message, the row stays RUNNING, and only the sweep ends it;
- the whole worker, process group and all (pod OOM, restart): the message stays
  unacked, Redis redelivers it, and the claim drops the redelivery.

The suite's session worker is not used: these workers die on purpose.
"""

import base64
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import psutil
import pytest

import cosmo_ecosystem.background_job_manager
from cosmo_ecosystem import job_log
from cosmo_ecosystem.job import Job
from cosmo_ecosystem.job_persistence import delete_job, load_row
from cosmo_ecosystem.tasks.sweep_tasks import sweep_lost_runs

from lost_run_domain import NAME_SLOW_TASK, SLOW_QUEUE
from lost_run_redelivery_domain import VISIBILITY_TIMEOUT_SECONDS

TEST_DIR = Path(__file__).parent
SAMPLE_CSV = TEST_DIR / "sample_mixed.csv"
# Long enough for a cold worker start and for Redis's restore cycle (every 10 s).
WAIT_SECONDS = 60


@dataclass
class _Worker:
    """A Celery worker subprocess and the file its output goes to."""

    process: subprocess.Popen
    log_path: Path

    def log(self) -> str:
        """Return what the worker has written so far."""
        return self.log_path.read_text(encoding="utf-8")


def _wait_until(condition, what, timeout=WAIT_SECONDS):
    """Poll condition until it holds; fail naming what did not happen."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.2)
    pytest.fail(f"Timed out after {timeout} s waiting for {what}")


@pytest.fixture
def start_worker(request, tmp_path):
    """Start workers of a test domain in their own process groups; kill them after."""
    if request.config.getoption("--no-services"):
        pytest.skip("Needs the services (--no-services flag set)")
    workers = []

    def start(domain):
        log_path = tmp_path / f"worker_{len(workers)}.log"
        pythonpath = (
            os.pathsep.join([str(TEST_DIR), os.environ["PYTHONPATH"]])
            if "PYTHONPATH" in os.environ
            else str(TEST_DIR)
        )
        with open(log_path, "w", encoding="utf-8") as log_file:
            # The interpreter directly, not `uv run`: the process is the worker's
            # main process, so its children are the prefork pool.
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "celery",
                    "-A",
                    "cosmo_ecosystem.celery_app.celery",
                    "worker",
                    "--loglevel=info",
                    "--concurrency=1",
                    "--pool=prefork",
                    f"--hostname=lost-run-{len(workers)}@test",
                    f"--queues={SLOW_QUEUE}",
                ],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                env={
                    **os.environ,
                    "PYTHONUNBUFFERED": "1",
                    "PYTHONPATH": pythonpath,
                    "COSMO_DOMAIN": domain,
                },
                start_new_session=True,
            )
        worker = _Worker(process, log_path)
        workers.append(worker)
        _wait_until(lambda: " ready." in worker.log(), f"worker {domain} to start")
        return worker

    yield start

    for worker in workers:
        if worker.process.poll() is None:
            os.killpg(worker.process.pid, signal.SIGKILL)
            worker.process.wait()
    # Kept for every run, failed or not: the artifacts dir holds them only when
    # a test failed, since Playwright clears it after an all-green run.
    artifacts = Path(request.config.getoption("--output")) / request.node.name
    artifacts.mkdir(parents=True, exist_ok=True)
    for worker in workers:
        (artifacts / worker.log_path.name).write_text(worker.log())


def _submit_slow(job):
    """Submit handler: send the job to the test domain's slow task."""
    manager = cosmo_ecosystem.background_job_manager.background_job_manager
    # The test process's app has csv_profiler's routes, not the test domain's.
    return manager.submit_job(NAME_SLOW_TASK, job.job_id, queue=SLOW_QUEUE)


@pytest.fixture
def slow_job(request, monkeypatch):
    """A job with the sample CSV uploaded, submitted to the slow task on submit."""
    monkeypatch.setattr(Job, "submit_handler", staticmethod(_submit_slow))
    job = Job(new_job_id=f"test_lost_{request.node.name.removeprefix('test_')}"[:50])
    job.upload_file(
        "text/csv",
        base64.b64encode(SAMPLE_CSV.read_bytes()).decode(),
        SAMPLE_CSV.name,
    )
    yield job
    delete_job(job.job_id)


def _claimed(job_id):
    """Return whether a worker has claimed the job's run."""
    return load_row(job_id)["heartbeat_at"] is not None


def test_a_run_whose_child_was_killed_ends_failed_through_the_sweep(
    start_worker, slow_job
):
    """An OOM-killed child leaves RUNNING behind; the sweep turns it into FAILED."""
    worker = start_worker("lost_run_domain")
    slow_job.submit()
    _wait_until(lambda: _claimed(slow_job.job_id), "the run to be claimed")

    (child,) = psutil.Process(worker.process.pid).children()
    child.kill()
    _wait_until(lambda: "WorkerLostError" in worker.log(), "the worker to see it")

    # The bug: nothing else would ever change this row.
    assert load_row(slow_job.job_id)["status"] == "RUNNING"

    swept = sweep_lost_runs(threshold=timedelta(0))

    assert slow_job.job_id in swept
    assert load_row(slow_job.job_id)["status"] == "FAILED"
    assert "Worker lost: no heartbeat since" in job_log.read(slow_job.job_id)


def test_a_redelivery_after_the_worker_died_is_dropped(start_worker, slow_job):
    """A pod restart does not start the killed run again; the row waits for the sweep."""
    dead = start_worker("lost_run_redelivery_domain")
    slow_job.submit()
    _wait_until(lambda: _claimed(slow_job.job_id), "the run to be claimed")

    os.killpg(dead.process.pid, signal.SIGKILL)
    dead.process.wait()
    row = load_row(slow_job.job_id)
    before = (row["status"], row["heartbeat_at"], job_log.read(slow_job.job_id))

    # kombu restores an unacked message at worker start only once it is older
    # than the visibility timeout (next chance ~100 s later), like a pod that
    # comes back after its message's timeout.
    time.sleep(VISIBILITY_TIMEOUT_SECONDS + 1)
    restarted = start_worker("lost_run_redelivery_domain")
    drop_line = f"Drop this delivery of job {slow_job.job_id}"
    _wait_until(lambda: drop_line in restarted.log(), "the redelivery to be dropped")

    row = load_row(slow_job.job_id)
    assert (row["status"], row["heartbeat_at"], job_log.read(slow_job.job_id)) == (
        before
    )
    assert before[0] == "RUNNING"
