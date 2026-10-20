#!/usr/bin/python3
"""The abstract job contract shared by the framework and its consumer apps.

``BaseJob`` is a *contract*, not an implementation. Construction and storage
differ fundamentally between the apps — one keeps job state in plain attributes,
another behind a Pydantic model — so only the members that framework code
actually calls on a job it did not build are abstract here. Everything else
(working directory, log refresh, domain methods) stays with the concrete class.

Log refresh is deliberately **not** part of the contract: the apps disagree on
its name (``reload_logs`` vs ``get_logs``) and no framework code calls it.

This module imports nothing else from the framework, on purpose: an app must be
able to satisfy the contract without pulling in the framework's database,
object-storage and Pydantic layers.
"""

from abc import ABC, abstractmethod


class BaseJob(ABC):
    """The job lifecycle contract every framework consumer can rely on.

    Framework code that is handed a job — ``files_route.serve_files``, the reset
    callbacks in ``layouts``, a ``Job.submit_handler`` — only ever uses these
    five members. An app that implements them can hand the framework its own job
    class instead of adopting the concrete ``cosmo_ecosystem.job.Job``.

    A route or callback that needs more than the contract says so in its own
    docstring; ``serve_files`` for instance also needs ``working_dir``.
    """

    @property
    @abstractmethod
    def job_id(self) -> str:
        """Return the job's unique id.

        A property rather than a bare attribute because the apps store it in
        different places (``self.job_id`` vs ``self.model.job_id``); exposing it
        under one name is what lets generic code, such as
        ``BackgroundJobManager.submit_job``, take an id and never touch the job.
        """

    @abstractmethod
    def save(self) -> None:
        """Persist the job — its files and its database row."""

    @abstractmethod
    def delete(self) -> None:
        """Remove the job from the database and from storage.

        Implementations may take keyword arguments to narrow what is deleted;
        the contract only requires that ``job.delete()`` works.
        """

    @abstractmethod
    def submit(self) -> None:
        """Hand the job to the background queue and record the new state."""

    @abstractmethod
    def time_to_live(self) -> int:
        """Return the number of days left before the job is deleted."""
