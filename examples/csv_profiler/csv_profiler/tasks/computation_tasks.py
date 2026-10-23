"""Computation tasks for CSV statistical profiling jobs."""

import json
import logging
import os

from cosmo_ecosystem import job_run
from cosmo_ecosystem.job import Job

from csv_profiler.computation_module import profile_csv

log = logging.getLogger(__name__)


def profile(job_id, work_dir):
    """Profile the job's uploaded CSV and write result.json into its work dir.

    The ``compute`` of the job run: it raises on any failure and never writes
    the job's status.
    """
    config = Job(job_id=job_id).model
    csv_path = os.path.join(work_dir, config.upload_file_name)
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV file not found: {config.upload_file_name}")
    log.info(f"Processing CSV: {config.upload_file_name}")

    result = profile_csv(
        file_path=csv_path,
        columns=config.columns,
        handle_missing=config.handle_missing,
        histogram_bins=config.histogram_bins,
        compute_correlation=config.compute_correlation,
        top_n_categories=config.top_n_categories,
        trigger_error=config.trigger_error,
    )

    with open(os.path.join(work_dir, "result.json"), "w", encoding="UTF-8") as f:
        json.dump(result, f, indent=2)
    log.info(f"Result of job {job_id} saved to result.json")


def start_computation_task(self, job_id):
    """Celery task: run CSV statistical profiling for a job.

    The job run writes the job's status; a failed run is a successful task
    (ADR 0002).

    Args:
        job_id: ID of the job to process
    """
    return job_run.run(job_id, profile)
