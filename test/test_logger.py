"""The logging configuration builders apps call at startup."""

import pytest

from cosmo_ecosystem.logger import get_logger_config_computation


def test_the_computation_logger_config_warns_that_it_will_go(tmp_path):
    """Apps get one version's notice before the per-job log file config is removed."""
    with pytest.warns(DeprecationWarning, match="job_run.run"):
        config = get_logger_config_computation(str(tmp_path / "logs"))

    assert config["handlers"]["file"]["filename"] == str(tmp_path / "logs")
