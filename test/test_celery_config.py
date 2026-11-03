"""The Redis settings ``BaseCeleryConfig`` derives from the environment.

``BaseCeleryConfig`` reads the environment when the class body runs, at import,
so each test imports it in a fresh interpreter with the variables it needs.
"""

import json
import os
import subprocess
import sys

from kombu.utils.url import parse_url

NASTY_PASSWORD = "p@ss/w:rd#1%2"

DUMP = """
import json
from cosmo_ecosystem.celery_config import BaseCeleryConfig as C
print(json.dumps({
    name: getattr(C, name, None)
    for name in (
        "broker_url",
        "result_backend",
        "redis_socket_timeout",
        "redis_socket_connect_timeout",
    )
}))
"""


def _config(**env):
    result = subprocess.run(
        [sys.executable, "-c", DUMP],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_a_password_with_url_characters_parses_back_unchanged():
    config = _config(REDIS_PASSWORD=NASTY_PASSWORD, REDIS_HOST="redis.example.org")

    for url in (config["broker_url"], config["result_backend"]):
        parsed = parse_url(url)
        assert parsed["hostname"] == "redis.example.org"
        assert parsed["password"] == NASTY_PASSWORD


def test_without_a_password_the_url_has_no_credentials():
    config = _config(REDIS_PASSWORD="")

    assert "@" not in config["broker_url"]


def test_the_redis_result_backend_gets_its_socket_timeouts_from_redis_settings():
    """Celery's Redis result backend reads ``redis_socket_*``, not transport options."""
    config = _config()

    assert config["redis_socket_timeout"] == 5
    assert config["redis_socket_connect_timeout"] == 5
