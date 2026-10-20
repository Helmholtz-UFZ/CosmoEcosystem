"""Domain submit wrapper for the CSV profiler computation task.

Thin wrapper over the framework's generic ``submit_job``; mounted on the
framework Job via ``Job.submit_handler`` at startup. Pulling the id out of the
job here is the whole point of the wrapper: the framework's manager takes a bare
``job_id`` and never touches a job object, so an app whose job class keeps the id
somewhere else reaches the same method through its own one-line wrapper.
"""

from cosmo_ecosystem.background_job_manager import background_job_manager

NAME_COMPUTATION_TASK = "csv_profiler.tasks.computation_tasks.start_computation"


def submit_computation_job(job) -> tuple[str | None, bool]:
    """Submit a CSV profiling job to the computation queue.

    ``track_task_name=True``: the worker-management page reads the stored name to
    label a revoked task, which would otherwise show up as "Unknown".

    Returns:
        tuple: (celery_task_id, failed_boolean); task_id is None on failure.
    """
    return background_job_manager.submit_job(
        NAME_COMPUTATION_TASK,
        job.job_id,
        queue="computation",
        track_task_name=True,
    )
