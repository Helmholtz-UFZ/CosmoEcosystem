"""Computation tasks for CSV statistical profiling jobs."""

import json
import logging
import os
import traceback
from logging.config import dictConfig

from celery import Task

from cosmo_ecosystem import job_persistence
from cosmo_ecosystem.constants import LOG_FILE_NAME
from cosmo_ecosystem.job import Job

from csv_profiler.computation_module import profile_csv
from cosmo_ecosystem.logger import (
    get_logger_config_computation,
    get_logger_config_worker,
)

log = logging.getLogger(__name__)


def flush_all_handlers():
    """Flush all logging handlers."""
    logger = logging.getLogger()
    for handler in logger.handlers:
        try:
            handler.flush()
        except (
            Exception
        ):  # flush can fail on any handler (file, DB, network); must not disrupt caller
            pass


class ComputationTask(Task):
    """Base class for computation tasks with custom error handling."""

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Handle task failure."""
        log.error(f"Task {task_id} failed: {exc}")
        log.error(f"Traceback: {einfo}")


def start_computation_task(self, job_id):
    """Celery task: run CSV statistical profiling for a job.

    Args:
        job_id: ID of the job to process
    """
    log.info(f"Starting computation for job {job_id}")
    try:
        job = Job(job_id=job_id)
        # Object storage wins: a stale copy on this pod must not shadow the
        # input the user just submitted.
        job_persistence.work_dir(job_id)
        log.debug("Job loaded")

        # Set up file-based logging for this computation
        log_file_path = os.path.join(job.working_dir, LOG_FILE_NAME)
        dictConfig(get_logger_config_computation(log_file_path))
        log.info(f"Computation started for job {job_id}")

        # Find the uploaded CSV file
        csv_path = os.path.join(job.working_dir, job.model.upload_file_name)
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"CSV file not found: {job.model.upload_file_name}")
        log.info(f"Processing CSV: {job.model.upload_file_name}")

        # Run the profiler with job config
        config = job.model
        result = profile_csv(
            file_path=csv_path,
            columns=config.columns,
            handle_missing=config.handle_missing,
            histogram_bins=config.histogram_bins,
            compute_correlation=config.compute_correlation,
            top_n_categories=config.top_n_categories,
            trigger_error=config.trigger_error,
        )

        # Save result as JSON
        result_path = os.path.join(job.working_dir, "result.json")
        with open(result_path, "w", encoding="UTF-8") as f:
            json.dump(result, f, indent=2)
        log.info("Result saved to result.json")

        job.status = "COMPLETED"
        flush_all_handlers()
        dictConfig(get_logger_config_worker())
        log.info("Computation finished.")
        job.save()
    except Exception as e:  # catch-all: must log and mark job FAILED  # noqa
        log.error("An error occurred")
        log.error(traceback.format_exc())
        flush_all_handlers()
        dictConfig(get_logger_config_worker())
        log.error(f"Computation task failed: {e}")
        job.status = "FAILED"
        job.save()
