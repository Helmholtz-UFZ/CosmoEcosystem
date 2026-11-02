"""Task specs: an app's Celery tasks, declared as data.

An app lists its tasks as ``task_specs`` in its domain module (see
``cosmo_ecosystem.celery_app``). The framework registers, routes and schedules
each task from its spec alone, so routes, the worker's queues and the beat
schedule have one source. The shape is the Layer B ``TaskSpec`` of
docs/plan/framework-generalization.md, so Layer B extends it instead of
replacing it.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from celery import Task


@dataclass(frozen=True)
class BeatEntry:
    """When Celery Beat runs a task.

    Attributes:
        schedule: A ``crontab``, a ``timedelta`` or seconds, as Celery's
            ``beat_schedule`` takes it. Evaluated in the app's configured
            ``timezone``.
        options: Extra ``apply_async`` options for the scheduled call. The queue
            is the spec's and is set by the framework.
    """

    schedule: Any
    options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskSpec:
    """One Celery task of an app.

    Attributes:
        fn: The task function. It is registered bound, so it takes the task
            instance as its first argument (``self``).
        name: The task name; the name ``send_task`` and the routes use.
        queue: The queue the task is routed to. The worker consumes every queue
            some spec names.
        base_task: A ``celery.Task`` subclass to register the task on, or
            ``None`` for Celery's default.
        beat: A schedule for Celery Beat, or ``None`` for an on-demand task.
    """

    fn: Callable[..., Any]
    name: str
    queue: str
    base_task: type[Task] | None
    beat: BeatEntry | None = None
