"""A test domain module for the lost-job-run tests: csv_profiler with a slow task.

Named by ``COSMO_DOMAIN=lost_run_domain`` in the worker that
``test_lost_job_runs.py`` starts and kills. The slow task gives the test a run
in flight to kill. It has its own name and queue, so the suite's session worker,
which consumes csv_profiler's queues, never takes its messages.
"""

import logging
import time

from cosmo_ecosystem import job_run
from cosmo_ecosystem.task_spec import TaskSpec

# Wires the Job seams and DbManager.job_table, as the real domain module does.
from csv_profiler.domain import (
    CeleryConfig,
    excluded_log_packages,  # noqa: F401  (domain module attribute)
    log_retention_days,  # noqa: F401  (domain module attribute)
)

NAME_SLOW_TASK = "lost_run_domain.slow_run"
SLOW_QUEUE = "lost_run_test"
# Far longer than a test waits: the run is always killed before it ends.
SLOW_RUN_SECONDS = 300

log = logging.getLogger(__name__)


def compute_slowly(job_id, work_dir):
    """A computation that takes SLOW_RUN_SECONDS, one log line per second."""
    for second in range(SLOW_RUN_SECONDS):
        log.info(f"Job {job_id}: second {second} of the slow run")
        time.sleep(1)


def slow_task(self, job_id):
    """Celery task: run the slow computation as a job run."""
    return job_run.run(job_id, compute_slowly)


celery_config = CeleryConfig

task_specs = [
    TaskSpec(fn=slow_task, name=NAME_SLOW_TASK, queue=SLOW_QUEUE, base_task=None),
]
