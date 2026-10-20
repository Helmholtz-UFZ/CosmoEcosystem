"""Test the framework's object storage manager against a real S3 server."""

import os
import shutil
import urllib.request
from datetime import timedelta

from cosmo_ecosystem.config import JOB_WORK_DIR_TEMPLATE
from cosmo_ecosystem.object_storage_manager import (
    delete_directory_from_storage,
    get_files,
    get_presigned_download_url,
    save_files,
)

JOB_ID = "test_presigned_download_url"
FILE_NAME = "result.csv"
CONTENT = "col_a,col_b\n1,2\n"

OVERWRITE_JOB_ID = "test_get_files_overwrite"
REMOTE_CONTENT = "col_a\nremote\n"
LOCAL_CONTENT = "col_a\nlocal\n"


def _write(work_dir, content):
    """Write content to this test's file inside work_dir."""
    with open(os.path.join(work_dir, FILE_NAME), "w", encoding="UTF-8") as f_handle:
        f_handle.write(content)


def _read(work_dir):
    """Read this test's file from work_dir."""
    with open(os.path.join(work_dir, FILE_NAME), "r", encoding="UTF-8") as f_handle:
        return f_handle.read()


def test_presigned_url_downloads_without_credentials():
    """A presigned URL serves the object to a client that has no credentials.

    This is the off-network download path (cosmonaut's QR code): the URL must
    carry its own auth, so the request below deliberately passes none.
    """
    work_dir = JOB_WORK_DIR_TEMPLATE.format(job_id=JOB_ID)
    os.makedirs(work_dir, exist_ok=True)
    _write(work_dir, CONTENT)

    save_files(JOB_ID)

    try:
        url = get_presigned_download_url(
            f"{JOB_ID}/{FILE_NAME}",
            timedelta(minutes=5),
        )
        with urllib.request.urlopen(url) as response:
            downloaded = response.read().decode("UTF-8")
    finally:
        delete_directory_from_storage(JOB_ID)
        shutil.rmtree(work_dir, ignore_errors=True)

    # A plain object URL would also download here (the test bucket is reachable),
    # so assert the signature is actually part of the URL.
    assert "X-Amz-Signature=" in url
    assert downloaded == CONTENT


def test_get_files_keeps_local_edits_unless_overwrite_is_asked_for():
    """Downloading must not clobber a local file that is not uploaded yet.

    The failure this guards against is silent: the user's edit is simply gone
    on the next page load, with no error anywhere.
    """
    work_dir = JOB_WORK_DIR_TEMPLATE.format(job_id=OVERWRITE_JOB_ID)
    os.makedirs(work_dir, exist_ok=True)
    _write(work_dir, REMOTE_CONTENT)
    save_files(OVERWRITE_JOB_ID)

    # The local edit that has not reached object storage.
    _write(work_dir, LOCAL_CONTENT)

    try:
        get_files(OVERWRITE_JOB_ID)
        after_default = _read(work_dir)

        get_files(OVERWRITE_JOB_ID, overwrite=True)
        after_overwrite = _read(work_dir)
    finally:
        delete_directory_from_storage(OVERWRITE_JOB_ID)
        shutil.rmtree(work_dir, ignore_errors=True)

    assert after_default == LOCAL_CONTENT
    assert after_overwrite == REMOTE_CONTENT
