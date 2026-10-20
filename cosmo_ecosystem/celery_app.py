"""Celery application with framework task registration.

Creates the shared Celery app and registers the FRAMEWORK tasks (maintenance,
test). A domain provides its own worker entry point that extends this app with
its computation task and exposes it as ``celery``:

    from cosmo_ecosystem.celery_app import app
    app.task(bind=True, name=NAME_COMPUTATION_TASK)(start_computation_task)
    celery = app  # celery -A <domain>.celery_app.celery worker ...

Separated from background_job_manager to break a circular import:
    tasks/*.py → job → background_job_manager → tasks/*.py
"""

from cosmo_ecosystem.background_job_manager import (
    NAME_CLEANUP_TASK,
    NAME_TEST_TASK,
    background_job_manager,
)
from cosmo_ecosystem.tasks.maintenance_tasks import cleanup_task
from cosmo_ecosystem.tasks.test_tasks import long_running_test_task

app = background_job_manager.app

app.task(bind=True, name=NAME_CLEANUP_TASK)(cleanup_task)
app.task(bind=True, name=NAME_TEST_TASK)(long_running_test_task)

# Exposed so a framework-only worker can run the maintenance/test tasks; a domain
# worker entry imports `app`, registers its own task(s), and re-exposes `celery`.
celery = app
