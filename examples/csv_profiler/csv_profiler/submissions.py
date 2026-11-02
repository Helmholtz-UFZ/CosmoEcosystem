"""Domain submission for the CSV profiler computation task.

A module function over the framework's manager, not a manager subclass or a
method mounted on it (ADR 0003). Mounted on the framework Job via
``Job.submit_handler`` in ``csv_profiler.domain``. Pulling the id out of the job
here is the whole point of the wrapper: the framework's manager takes a bare
``job_id`` and never touches a job object, so an app whose job class keeps the id
somewhere else reaches the same method through its own one-line wrapper.
"""

import cosmo_ecosystem.background_job_manager

NAME_COMPUTATION_TASK = "csv_profiler.tasks.computation_tasks.start_computation"


def submit_computation_job(job) -> tuple[str | None, bool]:
    """Submit a CSV profiling job to the computation queue.

    ``track_task_name=True``: the worker-management page reads the stored name to
    label a revoked task, which would otherwise show up as "Unknown".

    Returns:
        tuple: (celery_task_id, failed_boolean); task_id is None on failure.
    """
    # The manager is reached through its module at call time, not bound by a
    # `from … import` at import: that would assemble the Celery app while
    # csv_profiler.domain, which imports this module, is still half-imported.
    manager = cosmo_ecosystem.background_job_manager.background_job_manager
    return manager.submit_job(
        NAME_COMPUTATION_TASK,
        job.job_id,
        queue="computation",
        track_task_name=True,
    )
