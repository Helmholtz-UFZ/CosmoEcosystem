"""Test .env files for the project."""

import logging
import os
import shutil
from typing import List

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


def test_all_env_files(logger):
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
