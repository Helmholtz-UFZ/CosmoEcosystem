"""The one Celery app of a process, assembled from the app's domain module.

This module is the only place a ``Celery()`` is built. Web process, worker and
CLI reach the same app: the worker as

    celery -A cosmo_ecosystem.celery_app.celery worker --beat ...

(no ``--queues``: the worker consumes every queue a task spec names), the web
process through ``background_job_manager``, which wraps this app.

The app is assembled on first access to ``celery``, never at import, from the
domain module that the environment variable ``COSMO_DOMAIN`` names. Its contract
(attributes, import rules, failure modes) is written once, in
docs/conventions/domain_module.md; see also
docs/adr/0003-framework-assembles-the-celery-app.md.
"""

from logging.config import dictConfig

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init
from kombu import Exchange, Queue

from cosmo_ecosystem.celery_config import BaseCeleryConfig
from cosmo_ecosystem.domain import load_domain
from cosmo_ecosystem.error_handling import (
    DomainCeleryConfigInvalid,
    DomainCeleryConfigNotBase,
)
from cosmo_ecosystem.logger import get_logger_config_worker
from cosmo_ecosystem.task_spec import BeatEntry, TaskSpec
from cosmo_ecosystem.tasks.maintenance_tasks import cleanup_task
from cosmo_ecosystem.tasks.sweep_tasks import sweep_task
from cosmo_ecosystem.tasks.test_tasks import long_running_test_task

NAME_CLEANUP_TASK = "cosmo_ecosystem.tasks.maintenance_tasks.cleanup"
NAME_TEST_TASK = "cosmo_ecosystem.tasks.test_tasks.long_running_test"
NAME_SWEEP_TASK = "cosmo_ecosystem.tasks.sweep_tasks.sweep_lost_runs"

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
        fn=sweep_task,
        name=NAME_SWEEP_TASK,
        queue="maintenance",
        base_task=None,
        # Every 5 minutes: a lost job run shows FAILED at most
        # sweep_tasks.LOST_RUN_THRESHOLD plus 5 minutes after it died (ADR 0004).
        beat=BeatEntry(schedule=crontab(minute="*/5")),
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
    """Reject a domain config that breaks the contract (base class, spec settings)."""
    if not (isinstance(config, type) and issubclass(config, BaseCeleryConfig)):
        raise DomainCeleryConfigNotBase(config)
    for setting in SPEC_OWNED_SETTINGS:
        if hasattr(config, setting):
            raise DomainCeleryConfigInvalid(setting)


def _queue(name: str) -> Queue:
    """Declare queue ``name`` the way Celery would create a missing one."""
    return Queue(name, Exchange(name, type="direct"), routing_key=name)


def _connect_worker_logging(excluded_packages: tuple[str, ...]) -> None:
    """Configure logging in every worker process, muting ``excluded_packages``.

    Connected here, during assembly, never at import: when the framework
    connected it at import, both apps disconnected it and connected their own,
    and the effective config depended on import order.
    """

    def configure_worker_logging(sender=None, **kwargs):
        dictConfig(get_logger_config_worker(excluded_packages))

    # weak=False: the closure has no other reference and would be collected.
    worker_process_init.connect(
        configure_worker_logging,
        weak=False,
        dispatch_uid="cosmo_ecosystem.configure_worker_logging",
    )


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
    _connect_worker_logging(tuple(domain.excluded_log_packages))
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
