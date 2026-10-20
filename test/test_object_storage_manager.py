"""Tests for ``cosmo_ecosystem.object_storage_manager`` that need no running store.

The transfer paths need a real S3 server and are covered by the example suite.
What is checked here fails quietly in production instead of loudly in a test:

- presigning must not contact the store, and must sign path-style — the only
  addressing a non-AWS store resolves.
- an expiry beyond seven days signs fine and breaks on download, days later.
- ``setup_remote`` must keep the keys out of process arguments, which every user
  on the host can read.
- ``create_bucket`` used to take a bucket for present when a longer name
  containing it existed.
- under the production log config, botocore wrote ~60 DEBUG records per signed
  URL into the logs table, the signature among them (v0.8.0).
"""

import io
import logging
import logging.config
import stat
import subprocess
from datetime import timedelta

import pytest

from cosmo_ecosystem import logger, object_storage_manager
from cosmo_ecosystem.config import (
    OBJECT_STORAGE_ACCESS_KEY,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_HOST,
    OBJECT_STORAGE_REMOTE_NAME,
    OBJECT_STORAGE_SECRET_KEY,
)


def test_presigned_url_is_signed_locally_and_path_style():
    """Nothing listens on the placeholder endpoint, so any request would fail."""
    url = object_storage_manager.get_presigned_download_url(
        "job/result.csv", timedelta(hours=1)
    )

    assert url.startswith(
        f"{OBJECT_STORAGE_HOST}/{OBJECT_STORAGE_BUCKET}/job/result.csv?"
    )
    assert "X-Amz-Signature=" in url
    assert "X-Amz-Expires=3600" in url


@pytest.fixture
def web_log_stream():
    """The web process's log config, with its database handler left out.

    The PostgreSQL handler connects when it is built. The stream handler carries
    the same filter, so it receives exactly what the logs table would.
    """
    root = logging.getLogger()
    saved = (root.level, root.handlers[:], root.filters[:])
    config = logger.get_logger_config_web(debug=False)
    del config["handlers"]["postgres"]
    config["root"]["handlers"] = ["stream"]
    logging.config.dictConfig(config)
    stream = io.StringIO()
    root.handlers[0].setStream(stream)
    yield stream
    root.setLevel(saved[0])
    root.handlers[:] = saved[1]
    root.filters[:] = saved[2]


def test_presign_logs_one_line_and_no_signature(web_log_stream):
    url = object_storage_manager.get_presigned_download_url(
        "job/route.gpx", timedelta(hours=24)
    )

    signature = url.split("X-Amz-Signature=")[1]
    lines = web_log_stream.getvalue().splitlines()
    assert signature not in web_log_stream.getvalue()
    assert len(lines) == 1, lines
    assert "Generated presigned URL for job/route.gpx" in lines[0]


@pytest.mark.parametrize("expiry", [timedelta(days=7, seconds=1), timedelta(0)])
def test_presign_refuses_an_expiry_sigv4_cannot_carry(expiry):
    with pytest.raises(ValueError):
        object_storage_manager.get_presigned_download_url("job/result.csv", expiry)


def test_setup_remote_keeps_the_keys_off_the_command_line(monkeypatch, tmp_path):
    """The keys reach the config file and nothing else; other remotes survive."""
    config_path = tmp_path / "rclone" / "rclone.conf"
    config_path.parent.mkdir()
    config_path.write_text("[unrelated]\ntype = local\n")
    calls = []

    def fake_run(params, **kwargs):
        calls.append(params)
        return subprocess.CompletedProcess(
            params,
            0,
            stdout=f"Configuration file is stored at:\n{config_path}\n",
            stderr="",
        )

    monkeypatch.setattr(object_storage_manager.subprocess, "run", fake_run)

    object_storage_manager.setup_remote()

    arguments = " ".join(" ".join(params) for params in calls)
    assert OBJECT_STORAGE_SECRET_KEY not in arguments
    assert OBJECT_STORAGE_ACCESS_KEY not in arguments
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600
    written = config_path.read_text()
    assert f"[{OBJECT_STORAGE_REMOTE_NAME}]" in written
    assert f"secret_access_key = {OBJECT_STORAGE_SECRET_KEY}" in written
    assert "force_path_style = true" in written
    assert "[unrelated]" in written
    # The atomic write must not leave its temporary file behind.
    assert sorted(p.name for p in config_path.parent.iterdir()) == ["rclone.conf"]


def test_create_bucket_does_not_mistake_a_longer_name_for_the_bucket(monkeypatch):
    calls = []

    def fake_rclone(params, timeout):
        calls.append(params)
        return subprocess.CompletedProcess(
            params, 0, stdout=f"{OBJECT_STORAGE_BUCKET}-old/\nother/\n", stderr=""
        )

    monkeypatch.setattr(object_storage_manager, "run_rclone_with_retry", fake_rclone)

    object_storage_manager.create_bucket()

    assert calls[-1] == [
        "rclone",
        "mkdir",
        f"{OBJECT_STORAGE_REMOTE_NAME}:{OBJECT_STORAGE_BUCKET}",
    ]


def test_create_bucket_leaves_an_existing_bucket_alone(monkeypatch):
    calls = []

    def fake_rclone(params, timeout):
        calls.append(params)
        return subprocess.CompletedProcess(
            params, 0, stdout=f"other/\n{OBJECT_STORAGE_BUCKET}/\n", stderr=""
        )

    monkeypatch.setattr(object_storage_manager, "run_rclone_with_retry", fake_rclone)

    object_storage_manager.create_bucket()

    assert len(calls) == 1
