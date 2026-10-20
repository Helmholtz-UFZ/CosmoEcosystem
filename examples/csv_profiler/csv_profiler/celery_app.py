"""Celery worker entry point for the CSV profiler example.

Extends the framework Celery app (maintenance/test tasks already registered)
with the domain computation task, wires the framework Job seams for the worker
process, and exposes ``celery`` for:

    celery -A csv_profiler.celery_app.celery worker ...
"""

from importlib.metadata import version

from cosmo_ecosystem.celery_app import app
from cosmo_ecosystem.db_manager import DbManager
from cosmo_ecosystem.job import Job

from csv_profiler.background_job_manager import (
    NAME_COMPUTATION_TASK,
    submit_computation_job,
)
from csv_profiler.computation_module import validate_csv
from csv_profiler.db_manager import JobTable
from csv_profiler.pydantic_models import ProfileConfig
from csv_profiler.tasks.computation_tasks import start_computation_task

# Wire the framework Job seams for the worker process (before any task runs).
Job.config_model = ProfileConfig
Job.file_validator = staticmethod(validate_csv)
Job.submit_handler = staticmethod(submit_computation_job)
Job.app_version = version("csv-profiler")
DbManager.job_table = JobTable

# Register the domain computation task and route it to the computation queue.
app.task(bind=True, name=NAME_COMPUTATION_TASK)(start_computation_task)
app.conf.task_routes = {
    **(app.conf.task_routes or {}),
    "csv_profiler.tasks.computation_tasks.*": {"queue": "computation"},
}

# Exposed for: celery -A csv_profiler.celery_app.celery worker ...
celery = app
