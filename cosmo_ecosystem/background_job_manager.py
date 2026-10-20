"""Background job manager using Celery for distributed task processing.

Task registration lives in celery_app.py (the worker entry point) to avoid a
circular import: tasks/*.py → job → this module → tasks/*.py.
"""

import logging
from logging.config import dictConfig

from celery import Celery
from celery.exceptions import CeleryError
from celery.result import AsyncResult
from celery.signals import worker_process_init
from kombu.exceptions import OperationalError

from cosmo_ecosystem.celery_config import BaseCeleryConfig
from cosmo_ecosystem.logger import get_logger_config_worker

log = logging.getLogger(__name__)

NAME_CLEANUP_TASK = "cosmo_ecosystem.tasks.maintenance_tasks.cleanup"
NAME_TEST_TASK = "cosmo_ecosystem.tasks.test_tasks.long_running_test"


@worker_process_init.connect
def configure_worker_logging(sender=None, conf=None, **kwargs):
    """Configure database logging for Celery worker processes."""
    dictConfig(get_logger_config_worker())


class BackgroundJobManager:
    """Centralized manager for all background job operations using Celery."""

    def __init__(self):
        """Initialize the background job manager."""
        self.app = Celery("cosmo_ecosystem")
        self.app.config_from_object(BaseCeleryConfig)
        self.app.conf.update(
            broker_connection_retry_on_startup=True,
            broker_connection_retry=True,
        )

    def _send_task(
        self,
        task_name: str,
        args: list,
        queue: str,
        *,
        track_task_name: bool,
        **opts,
    ) -> tuple[str | None, bool]:
        """Send a task with the framework's retry policy. Shared plumbing.

        Args:
            task_name: Dotted Celery task name (must match the registered name)
            args: Positional args passed to the task
            queue: Target queue name
            track_task_name: Store the task name in the result backend
            **opts: Passed through to ``Celery.send_task``; an explicit key
                overrides the framework default for it

        Returns:
            tuple: (celery_task_id, failed_boolean)
                   celery_task_id is None if submission failed
        """
        send_opts = {
            "retry": True,
            "retry_policy": {
                "max_retries": 3,
                "interval_start": 10,
                "interval_step": 15,
                "interval_max": 30,
            },
        } | opts

        try:
            result = self.app.send_task(task_name, args=args, queue=queue, **send_opts)
            if track_task_name:
                # Store task name in Redis for revoked task retrieval
                self.app.backend.client.set(
                    f"task_name:{result.id}",
                    task_name,
                    ex=86400,  # 24 hour TTL
                )
            log.info(f"Submitted task {task_name} with task_id={result.id}")
            return result.id, False
        except (OperationalError, CeleryError) as e:
            log.error(f"Failed to submit task {task_name}: {e}")
            return None, True

    def submit_job(
        self,
        task_name: str,
        job_id: str,
        queue: str = "default",
        *,
        track_task_name: bool = True,
        **opts,
    ) -> tuple[str | None, bool]:
        """Submit a job task by id, without ever touching a job object.

        The manager takes a plain ``job_id``, never a job: the apps keep the id
        in different places (``job.job_id`` vs ``job.model.job_id``), so their
        thin wrappers pull it out and pass it here. That is what keeps this
        method usable by an app whose job class is not the framework's.

        Args:
            task_name: Dotted Celery task name (must match the registered name)
            job_id: The job id, passed to the task as its only positional arg
            queue: Target queue name
            track_task_name: Store ``task_name`` under ``task_name:<task_id>``
                in the result backend. The worker-management page reads that key
                when a revoked task no longer reports its own name; without it
                such a task shows up as "Unknown". On by default, matching
                ``submit_named_job``: both apps rely on this to keep a revoked
                task from showing up as "Unknown", and that outweighs the extra
                backend write per submission. Pass ``False`` explicitly to skip
                the write.
            **opts: Passed through to ``Celery.send_task`` (``countdown``,
                ``eta``, …); an explicit key overrides the framework default

        Returns:
            tuple: (celery_task_id, failed_boolean)
                   celery_task_id is None if submission failed
        """
        return self._send_task(
            task_name, [job_id], queue, track_task_name=track_task_name, **opts
        )

    def submit_named_job(
        self,
        task_name: str,
        args: list | None = None,
        queue: str = "default",
    ) -> tuple[str | None, bool]:
        """Submit a named task to a Celery queue with retry + revoke bookkeeping.

        Generic submission plumbing for a task with an arbitrary argument list.
        A task that takes a job id is better served by ``submit_job``, which is
        the seam an app can adopt with its own job class.

        Args:
            task_name: Dotted Celery task name (must match the registered name)
            args: Positional args passed to the task
            queue: Target queue name

        Returns:
            tuple: (celery_task_id, failed_boolean)
                   celery_task_id is None if submission failed
        """
        return self._send_task(task_name, args or [], queue, track_task_name=True)

    def get_job_status(self, task_id: str) -> dict:
        """Get status of a Celery task.

        Args:
            task_id: The Celery task ID

        Returns:
            dict: Task status information including:
                  - task_id: The task ID
                  - status: Task status (PENDING, STARTED, SUCCESS, FAILURE, etc.)
                  - result: Task result if ready, None otherwise
                  - traceback: Traceback if task failed, None otherwise
        """
        result = AsyncResult(task_id, app=self.app)
        return {
            "task_id": task_id,
            "status": result.status,
            "result": result.result if result.ready() else None,
            "traceback": result.traceback if result.failed() else None,
            "date_done": result.date_done,
        }

    def get_task_result_info(self, task_id: str) -> dict:
        """Get task name and status from result backend."""
        task_name = "Unknown"
        status = "REVOKED"

        try:
            result = AsyncResult(task_id, app=self.app)
            if result.name:
                task_name = result.name.split(".")[-1]
            else:
                stored_name = self.app.backend.client.get(f"task_name:{task_id}")
                if stored_name:
                    task_name = stored_name.decode().split(".")[-1]
            if result.status:
                status = result.status
        except CeleryError as e:
            log.debug(f"Could not get result info for task {task_id}: {e}")

        return {"task_name": task_name, "status": status}

    def get_all_tasks_overview(self) -> dict:
        """Get comprehensive task overview using Celery inspect API.

        Returns:
            dict: Contains active, reserved, scheduled, revoked tasks and worker list
                  - active: List of running tasks with worker field
                  - reserved: List of claimed but not started tasks
                  - scheduled: List of future-scheduled tasks
                  - revoked: List of revoked task dicts with "id" and "worker" keys
                  - workers: List of online worker names

        Raises:
            ConnectionError: If unable to connect to Redis/Celery broker
        """
        try:
            inspect = self.app.control.inspect()

            # Get task data from all workers
            active = inspect.active() or {}
            reserved = inspect.reserved() or {}
            scheduled = inspect.scheduled() or {}
            revoked_dict = inspect.revoked() or {}

            def flatten_tasks(worker_dict):
                """Flatten {worker: [tasks]} to [tasks] with worker info."""
                result = []
                for worker, tasks in (worker_dict or {}).items():
                    for task in tasks:
                        if isinstance(task, dict):
                            task["worker"] = worker
                            result.append(task)
                        else:
                            # Revoked returns plain ID strings, not dicts
                            result.append({"id": task, "worker": worker})
                return result

            # Get list of online workers (single call to avoid race with worker shutdown)
            ping_result = inspect.ping()
            workers = list(ping_result.keys()) if ping_result else []

            return {
                "active": flatten_tasks(active),
                "reserved": flatten_tasks(reserved),
                "scheduled": flatten_tasks(scheduled),
                "revoked": flatten_tasks(revoked_dict),
                "workers": workers,
            }
        except (OperationalError, ConnectionError) as e:
            log.warning(f"Failed to connect to Celery broker: {str(e)}")
            raise ConnectionError(
                "Unable to connect to Celery broker. Ensure Redis is running and accessible."
            ) from e

    def revoke_job(self, task_id: str, terminate: bool = False) -> None:
        """Revoke/cancel a running or queued task.

        Args:
            task_id: The Celery task ID
            terminate: If True, send SIGTERM to worker process (kill)
                       If False, just prevent execution (cancel)
        """
        self.app.control.revoke(task_id, terminate=terminate)
        log.info(f"Task {task_id} revoked (terminate={terminate})")

    def submit_test_task(self) -> tuple[str | None, bool]:
        """Submit a test sleep task to the Celery queue.

        Returns:
            tuple: (celery_task_id, failed_boolean)
                   celery_task_id is None if submission failed
        """
        try:
            result = self.app.send_task(
                NAME_TEST_TASK,
                queue="test",
            )
            # Store task name in Redis for revoked task retrieval
            self.app.backend.client.set(
                f"task_name:{result.id}",
                NAME_TEST_TASK,
                ex=86400,  # 24 hour TTL
            )
            log.info(f"Submitted test task with task_id={result.id}")
            return result.id, False
        except (OperationalError, CeleryError) as e:
            log.error(f"Failed to submit test task: {e}")
            return None, True

    def submit_cleanup_task(self) -> tuple[str | None, bool]:
        """Submit a maintenance cleanup task to the Celery queue.

        Returns:
            tuple: (celery_task_id, failed_boolean)
                   celery_task_id is None if submission failed
        """
        try:
            result = self.app.send_task(
                NAME_CLEANUP_TASK,
                queue="default",
            )
            # Store task name in Redis for revoked task retrieval
            self.app.backend.client.set(
                f"task_name:{result.id}",
                NAME_CLEANUP_TASK,
                ex=86400,  # 24 hour TTL
            )
            log.info(f"Submitted cleanup task with task_id={result.id}")
            return result.id, False
        except (OperationalError, CeleryError) as e:
            log.error(f"Failed to submit cleanup task: {e}")
            return None, True


_background_job_manager = None


def __getattr__(name):
    """Lazy singleton — BackgroundJobManager is created on first access, not on import."""
    global _background_job_manager
    if name == "background_job_manager":
        if _background_job_manager is None:
            _background_job_manager = BackgroundJobManager()
        return _background_job_manager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
