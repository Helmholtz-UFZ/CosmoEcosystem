"""The CSV profiler's domain module: what the framework needs to assemble a process.

Named by ``COSMO_DOMAIN=csv_profiler.domain`` in every process (web, worker,
CLI). ``cosmo_ecosystem.celery_app`` imports it on first access to the Celery app
and builds that app from the attributes below; see that module for the contract.

Importing it also wires the framework Job seams and ``DbManager.job_table``, so
the worker, which never imports ``app.py``, has them before any task runs. The web
process imports it at the top of ``app.py`` for the same reason.
"""

from importlib.metadata import version

from cosmo_ecosystem.celery_config import BaseCeleryConfig
from cosmo_ecosystem.db_manager import DbManager
from cosmo_ecosystem.job import Job
from cosmo_ecosystem.task_spec import TaskSpec

from csv_profiler.computation_module import validate_csv
from csv_profiler.db_manager import JobTable
from csv_profiler.pydantic_models import ProfileConfig
from csv_profiler.submissions import NAME_COMPUTATION_TASK, submit_computation_job
from csv_profiler.tasks.computation_tasks import start_computation_task

# Wire the framework Job seams before any Job is constructed.
Job.config_model = ProfileConfig
Job.file_validator = staticmethod(validate_csv)
Job.submit_handler = staticmethod(submit_computation_job)
Job.app_version = version("csv-profiler")
# Set on DbManager itself, not a subclass: see docs/conventions/database_schema.md.
DbManager.job_table = JobTable


class CeleryConfig(BaseCeleryConfig):
    """Domain Celery settings: none yet.

    This is where a domain keeps its timezone and time limits, next to the
    reasoning for them. Routes and the beat schedule do not belong here: they
    come from ``task_specs``.
    """


celery_config = CeleryConfig

task_specs = [
    TaskSpec(
        fn=start_computation_task,
        name=NAME_COMPUTATION_TASK,
        queue="computation",
        base_task=None,
    ),
]

# Worker logging mutes nothing beyond the framework's own list.
excluded_log_packages = ()

# Log rows older than this are deleted by the framework cleanup.
log_retention_days = 60
