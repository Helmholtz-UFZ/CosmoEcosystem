"""Test .env files for the project."""

import logging
import os
import pathlib
import shutil
from typing import List

import pytest
from dotenv import load_dotenv

from cosmo_ecosystem.config import env_vars, getenv


def _test_single_env_file(env_filename: str, logger, additional_lines: List[str]):
    """Test a single .env file.

    Args:
        env_filename: Name of the env file (e.g., "env_dev")
        logger: Logger instance for test output
        additional_lines: Optional list of lines to append to the env file
    """
    # Copy env file to .env
    shutil.copy(env_filename, ".env")

    # Add additional lines if provided
    if additional_lines:
        with open(".env", "a") as f:
            for line in additional_lines:
                f.write(f"{line}\n")

    # Remove the env_vars from the environment
    for env_var in env_vars:
        os.environ.pop(env_var, None)

    # Reload the .env file
    load_dotenv(override=True)

    # Test each environment variable
    for env_var in env_vars:
        logger.info(f"Testing {env_var} from {env_filename}")
        logging.info(getenv(env_var))


@pytest.fixture
def restored_env():
    """Put the run's .env and environment back after the test.

    The test overwrites .env and reloads os.environ from fixed env files. run_pytest.sh
    writes per-run ports into .env, and later tests (and the Celery worker, which
    inherits os.environ) must keep using them, not env_test's slot ports.
    """
    env_file = pathlib.Path(".env")
    saved_file = env_file.read_bytes()
    saved_environ = dict(os.environ)
    yield
    env_file.write_bytes(saved_file)
    os.environ.clear()
    os.environ.update(saved_environ)


def test_all_env_files(logger, restored_env):
    """Test all environment files at once."""
    env_files = [
        "env_dev",
        "env_test",
    ]
    additional_lines_map = {}

    for env_filename in env_files:
        logger.info(f"Testing environment file: {env_filename}")
        additional_lines = additional_lines_map.get(env_filename, [])
        _test_single_env_file(env_filename, logger, additional_lines)
