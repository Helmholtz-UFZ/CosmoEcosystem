"""Test tasks for integration testing."""

import time


def long_running_test_task(self, duration: int = 60):
    """Run for a specified duration.

    Args:
        duration: How long to run in seconds (default 60)

    Returns:
        str: Completion message
    """
    start_time = time.time()
    while time.time() - start_time < duration:
        time.sleep(1)
    return f"Completed after {duration} seconds"
