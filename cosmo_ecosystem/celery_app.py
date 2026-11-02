"""The one Celery app of a process, assembled from the app's domain module.

This module is the only place a ``Celery()`` is built. Web process, worker and
CLI reach the same app: the worker as

    celery -A cosmo_ecosystem.celery_app.celery worker --beat ...

(no ``--queues``: the worker consumes every queue a task spec names), the web
process through ``background_job_manager``, which wraps this app.

The app is assembled on first access to ``celery``, never at import, from the
module that the environment variable ``COSMO_DOMAIN`` names (a dotted module
path, ``<app>.domain`` by convention). That **domain module** exposes:

- ``task_specs``: list of ``TaskSpec``, the app's tasks (the framework adds its
  own cleanup and test task);
- ``celery_config``: a ``BaseCeleryConfig`` subclass holding domain settings
  only (timezone, time limits). It must not set ``task_routes`` or
  ``beat_schedule``: both are derived from the task specs;
- ``excluded_log_packages``: tuple of package names muted in worker logging;
- ``log_retention_days``: int, how long the framework cleanup keeps log rows.

Importing the domain module also wires the app's Job seams and
``DbManager.job_table``. It must not touch ``celery`` or the manager singleton
at import: assembly imports it, so that access would run while the domain
module is still half-initialised.

See docs/adr/0003-framework-assembles-the-celery-app.md.
"""

from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue

from cosmo_ecosystem.celery_config import BaseCeleryConfig
from cosmo_ecosystem.domain import load_domain
from cosmo_ecosystem.error_handling import DomainCeleryConfigInvalid
from cosmo_ecosystem.task_spec import BeatEntry, TaskSpec
from cosmo_ecosystem.tasks.maintenance_tasks import cleanup_task
from cosmo_ecosystem.tasks.test_tasks import long_running_test_task

NAME_CLEANUP_TASK = "cosmo_ecosystem.tasks.maintenance_tasks.cleanup"
NAME_TEST_TASK = "cosmo_ecosystem.tasks.test_tasks.long_running_test"

# Settings the task specs own; a domain config that sets one is rejected.
SPEC_OWNED_SETTINGS = ("task_routes", "beat_schedule")

FRAMEWORK_TASK_SPECS = [
    TaskSpec(
        fn=cleanup_task,
        name=NAME_CLEANUP_TASK,
        queue="maintenance",
        base_task=None,
        # 03:00 in the app's configured timezone.
        beat=BeatEntry(schedule=crontab(minute=0, hour=3)),
    ),
    TaskSpec(
        fn=long_running_test_task,
        name=NAME_TEST_TASK,
        queue="test",
        base_task=None,
    ),
]

_app: Celery | None = None


def _check_domain_config(config: type[BaseCeleryConfig]) -> None:
    """Reject a domain config that sets a setting the task specs own.

    ``BaseCeleryConfig`` itself is skipped: only what the domain adds counts.
    """
    for setting in SPEC_OWNED_SETTINGS:
        for klass in config.__mro__:
            if klass is not BaseCeleryConfig and setting in vars(klass):
                raise DomainCeleryConfigInvalid(setting)


def _queue(name: str) -> Queue:
    """Declare queue ``name`` the way Celery would create a missing one."""
    return Queue(name, Exchange(name, type="direct"), routing_key=name)


def _assemble() -> Celery:
    """Build the process's Celery app from the domain module."""
    domain = load_domain()
    config = domain.celery_config
    _check_domain_config(config)

    app = Celery("cosmo_ecosystem")
    app.config_from_object(config)

    specs = FRAMEWORK_TASK_SPECS + list(domain.task_specs)
    for spec in specs:
        options = {"bind": True, "name": spec.name}
        if spec.base_task is not None:
            options["base"] = spec.base_task
        app.task(**options)(spec.fn)

    queue_names = {spec.queue for spec in specs} | {config.task_default_queue}
    app.conf.update(
        broker_connection_retry_on_startup=True,
        broker_connection_retry=True,
        task_routes={spec.name: {"queue": spec.queue} for spec in specs},
        task_queues=[_queue(name) for name in sorted(queue_names)],
        beat_schedule={
            spec.name: {
                "task": spec.name,
                "schedule": spec.beat.schedule,
                "options": {**spec.beat.options, "queue": spec.queue},
            }
            for spec in specs
            if spec.beat is not None
        },
    )
    return app


def get_app() -> Celery:
    """Return the process's Celery app, assembling it on first call."""
    global _app
    if _app is None:
        _app = _assemble()
    return _app


def __getattr__(name):
    """Lazy ``celery`` — assembled on first access, not on import."""
    if name == "celery":
        return get_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
