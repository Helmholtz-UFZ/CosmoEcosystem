"""Integration test for BackgroundJobManager with real Celery workers."""

import time

import pytest
from celery import states

from cosmo_ecosystem.background_job_manager import (
    NAME_TEST_TASK,
    background_job_manager,
)


def test_worker_management_workflow(celery_worker, logger):
    """Test workflow: submit task, verify it runs, kill it, verify termination.

    This test verifies:
    1. Tasks can be submitted to the worker
    2. get_job_status() works
    3. revoke_job() with terminate=True works
    4. The worker processes tasks from the maintenance queue
    """
    # Ensure worker is running
    if celery_worker.poll() is not None:
        pytest.fail("Celery worker not running")

    logger.info("Starting worker management integration test")

    # Give worker time to fully start
    logger.info("Waiting for worker to be ready...")
    time.sleep(5)

    # Test that get_all_tasks_overview returns proper structure
    overview = background_job_manager.get_all_tasks_overview()
    assert "active" in overview, "Overview missing 'active' key"
    assert "reserved" in overview, "Overview missing 'reserved' key"
    assert "scheduled" in overview, "Overview missing 'scheduled' key"
    assert "revoked" in overview, "Overview missing 'revoked' key"
    logger.info(f"Task overview structure verified: {list(overview.keys())}")
    # Step 1: Submit long running task which takes some time to execute
    logger.info("Submitting long running test task to maintenance queue...")
    result = background_job_manager.app.send_task(
        NAME_TEST_TASK,
        args=[60],
        queue="maintenance",  # Run for 60 seconds
    )
    task_id = result.id
    logger.info(f"Task submitted with ID: {task_id}")

    # Step 2: Wait for task to start executing (status changes from PENDING)
    logger.info("Waiting for task to start...")
    max_wait = 15
    task_started = False
    for attempt in range(max_wait):
        time.sleep(1)
        status_info = background_job_manager.get_job_status(task_id)
        current_status = status_info["status"]
        logger.info(f"Task status (attempt {attempt + 1}): {current_status}")

        if current_status in [states.STARTED, states.SUCCESS, states.FAILURE]:
            task_started = True
            logger.info(
                f"Task {task_id} has started executing (status: {current_status})"
            )
            break

    if not task_started:
        final_status = background_job_manager.get_job_status(task_id)
        logger.error(f"Task never started. Final status: {final_status}")
        pytest.fail(
            f"Task {task_id} never started after {max_wait} seconds. Final status: {final_status['status']}"  # noqa
        )

    # Step 3: Immediately kill the task while it's running
    logger.info(f"Killing task {task_id} with terminate=True...")
    background_job_manager.revoke_job(task_id, terminate=True)
    logger.info("Revoke command sent")

    # Step 4: Wait and verify task is terminated (status becomes REVOKED)
    logger.info("Waiting for task to be revoked...")
    time.sleep(5)  # Give it time to process the revoke

    final_status_info = background_job_manager.get_job_status(task_id)
    final_status = final_status_info["status"]
    logger.info(f"Final task status after revoke: {final_status}")

    # Also verify task appears in overview
    final_overview = background_job_manager.get_all_tasks_overview()
    active_count = len(final_overview["active"])
    revoked_count = len(final_overview["revoked"])
    scheduled_count = len(final_overview["scheduled"])
    logger.info(
        f"Final overview - active: {active_count}, "
        f"revoked: {revoked_count}, scheduled: {scheduled_count}"
    )

    # Task should be REVOKED (or possibly SUCCESS if it completed before being killed)
    assert final_status in [
        states.REVOKED,
        states.SUCCESS,
    ], f"Expected status REVOKED or SUCCESS after terminate, got: {final_status}"

    if final_status == states.REVOKED:
        logger.info("Task successfully terminated")
    else:
        logger.info("Task completed before termination (acceptable race condition)")

    # Step 5: Verify get_job_status returns correct structure
    assert "task_id" in final_status_info
    assert "status" in final_status_info
    assert "result" in final_status_info
    assert "traceback" in final_status_info
    assert "date_done" in final_status_info
    logger.info("get_job_status returns correct structure")

    logger.info("Worker management integration test completed successfully!")
