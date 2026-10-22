"""This module provides functions to manage object storage using rclone.

Transfers go through rclone; boto3 is only used to sign download URLs. Both talk
plain S3, so any S3-compatible store works (UFZ S3 in production, RustFS locally
and in CI — see docs/conventions/object_storage.md).
"""

import configparser
import logging
import os
import subprocess
import sys
import tempfile
import time
from datetime import timedelta
from functools import cache

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError

from cosmo_ecosystem.config import (
    JOB_WORK_DIR_TEMPLATE,
    OBJECT_STORAGE_ACCESS_KEY,
    OBJECT_STORAGE_BUCKET,
    OBJECT_STORAGE_HOST,
    OBJECT_STORAGE_REMOTE_NAME,
    OBJECT_STORAGE_SECRET_KEY,
)

log = logging.getLogger(__name__)

# Subprocess timeouts in seconds. Every rclone call gets one: without it a hung
# rclone — an unreachable store, a half-open TCP connection — blocks the calling
# worker forever (measured in COSMONAUT on Kubernetes).
# Two tiers, because the right bound depends on what scales with the data:
TRANSFER_TIMEOUT = 600  # copy / sync / purge — grows with the job's file volume
CONTROL_TIMEOUT = 60  # listings, single-file delete, config, mkdir
CONNECTION_CHECK_TIMEOUT = 5  # the pre-flight below, which must fail fast

# rclone and boto3 have to sign for the same region. S3-compatible stores that are
# not AWS accept any name; us-east-1 is the one every client falls back to.
OBJECT_STORAGE_REGION = "us-east-1"

# SigV4 caps a presigned URL at seven days. boto3 signs a longer expiry without
# complaint and the store refuses the URL only when it is used — for a QR code or
# an e-mailed link that is days later, far away from any log.
MAX_PRESIGN_EXPIRY = timedelta(days=7)


# Convention deviation (CLAUDE.md): custom exceptions normally live in
# error_handling.py. This one deliberately stays here, because
# error_handling.py imports it *from* this module — moving it would invert that
# edge into a cycle, and would make this worker-side module pull in Dash, which
# error_handling.py needs for set_props().
# Consumers must re-export this class rather than define their own of the same
# name: two distinct classes make `except ObjectStorageError` miss silently.
class ObjectStorageError(Exception):
    """Exception raised for errors in the ObjectStorageManager class."""

    def __init__(self, message="An error occurred while managing object storage."):
        """Initialize the ObjectStorageError class."""
        super().__init__(message)


def check_result(params: list, result: subprocess.CompletedProcess) -> None:
    """Check the result of a subprocess command and raise an error if it failed.

    Args:
        result: The result of the subprocess command

    Raises:
        ObjectStorageError: If the command failed
    """
    error_msg = result.stderr.replace(OBJECT_STORAGE_SECRET_KEY, "****")
    error_msg = error_msg.replace(OBJECT_STORAGE_ACCESS_KEY, "****")
    output = result.stdout.replace(OBJECT_STORAGE_SECRET_KEY, "****")
    output = output.replace(OBJECT_STORAGE_ACCESS_KEY, "****")
    call = " ".join(params)
    call = call.replace(OBJECT_STORAGE_SECRET_KEY, "****")
    call = call.replace(OBJECT_STORAGE_ACCESS_KEY, "****")
    if result.returncode != 0:
        if "QuotaExceeded" in error_msg:
            log.error(
                f"Object storage quota exceeded for command: {call}\n{error_msg}\n{output}",  # noqa
            )
        else:
            log.error(
                f"Command failed: {call}\n{error_msg}\n{output}",
            )
        raise ObjectStorageError


@cache
def _s3_client():
    """Build the S3 client once per process. It opens no connection by itself."""
    return boto3.client(
        "s3",
        endpoint_url=OBJECT_STORAGE_HOST,
        aws_access_key_id=OBJECT_STORAGE_ACCESS_KEY,
        aws_secret_access_key=OBJECT_STORAGE_SECRET_KEY,
        region_name=OBJECT_STORAGE_REGION,
        # Path style, like rclone's force_path_style: virtual-host style puts the
        # bucket into the hostname, which a non-AWS store does not resolve.
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def get_presigned_download_url(object_key: str, expiry: timedelta) -> str:
    """Generate a presigned GET URL for an object in S3-compatible storage.

    The URL carries its own credentials, so it can be handed to a client outside
    the network (e.g. encoded into a QR code) without exposing the storage keys.

    Signing is local: no request reaches the store, so this works while the store
    is down and does not prove the object exists.

    Args:
        object_key: Key of the object (e.g. "{job_id}/result.csv")
        expiry: Duration for which the URL is valid, at most seven days

    Returns:
        str: Presigned URL that can be downloaded without credentials

    Raises:
        ValueError: If expiry is not positive or exceeds MAX_PRESIGN_EXPIRY
        ObjectStorageError: If the URL cannot be signed
    """
    if not timedelta(0) < expiry <= MAX_PRESIGN_EXPIRY:
        raise ValueError(
            f"Presign expiry must be within (0, {MAX_PRESIGN_EXPIRY}], got {expiry}"
        )
    try:
        url = _s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": OBJECT_STORAGE_BUCKET, "Key": object_key},
            ExpiresIn=int(expiry.total_seconds()),
        )
    except BotoCoreError as e:
        log.error(f"Presigning failed for {object_key}: {e}")
        raise ObjectStorageError(f"Presigning failed for {object_key}") from e
    log.debug(f"Generated presigned URL for {object_key}")
    return url


def _verify_remote_reachable() -> None:
    """Fail fast if the object storage remote cannot be reached.

    Without this pre-flight a transfer against a dead address burns the full
    retry schedule — three attempts of up to ``TRANSFER_TIMEOUT`` each — before
    reporting a failure the first second already knew about.

    Raises:
        ObjectStorageError: If the remote is unreachable or answers too slowly
    """
    check_params = [
        "rclone",
        "lsd",
        f"{OBJECT_STORAGE_REMOTE_NAME}:",
        "--contimeout",
        "3s",
    ]
    try:
        result = subprocess.run(
            check_params,
            capture_output=True,
            text=True,
            timeout=CONNECTION_CHECK_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        log.error("Object storage connection check timed out — remote unreachable")
        raise ObjectStorageError("Object storage connection check timed out") from None

    if result.returncode != 0:
        log.error(f"Object storage connection check failed: {result.stderr}")
        raise ObjectStorageError("Object storage connection check failed")

    log.debug("Object storage connection check passed")


def run_rclone_with_retry(
    params: list,
    timeout: float = TRANSFER_TIMEOUT,
    check_connection: bool = False,
) -> subprocess.CompletedProcess:
    """Run rclone command with retry logic for NFS lock file conflicts.

    Args:
        params: The rclone command parameters
        timeout: Seconds before a single attempt is killed
        check_connection: Verify the remote is reachable before the first attempt

    Raises:
        ObjectStorageError: If all retry attempts fail, the command times out,
            or the connection check fails
    """
    max_retries = 3
    retry_delay = 2

    if check_connection:
        _verify_remote_reachable()

    for attempt in range(max_retries):
        try:
            result = subprocess.run(
                params,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            check_result(params, result)
        except subprocess.TimeoutExpired:
            # Not retried: a command that ran into its timeout has no reason to
            # succeed within the same budget on the next attempt.
            log.error(f"Command timed out after {timeout}s: {' '.join(params)}")
            raise ObjectStorageError(f"Command timed out after {timeout}s") from None
        except ObjectStorageError:
            if attempt < max_retries - 1:
                log.warning(
                    f"{' '.join(params)} failed. Retry attempt {attempt + 1}",
                )
                time.sleep(retry_delay)
            else:
                raise

    return result


def _rclone_config_path() -> str:
    """Return the config file rclone reads, whether it exists yet or not."""
    params = ["rclone", "config", "file"]
    result = subprocess.run(
        params,
        capture_output=True,
        text=True,
        timeout=CONTROL_TIMEOUT,
    )
    check_result(params, result)
    # "Configuration file is stored at:" or "Configuration file doesn't exist, but
    # rclone will use this path:" — the path is the last line either way.
    return result.stdout.strip().splitlines()[-1]


def setup_remote() -> None:
    """Write the object storage remote into rclone's config file.

    The file is written here instead of through ``rclone config create``, which
    takes the keys as arguments — and a process's arguments are readable by every
    user on the host (``ps``, ``/proc/<pid>/cmdline``). The file ends up
    owner-only, as rclone itself would leave it.
    """
    log.debug("Setting up rclone remote.")
    config_path = _rclone_config_path()

    config = configparser.ConfigParser(interpolation=None)
    # rclone option names are case-sensitive; configparser lowercases by default.
    config.optionxform = str
    config.read(config_path)
    config[OBJECT_STORAGE_REMOTE_NAME] = {
        "type": "s3",
        "provider": "Other",
        "access_key_id": OBJECT_STORAGE_ACCESS_KEY,
        "secret_access_key": OBJECT_STORAGE_SECRET_KEY,
        "region": OBJECT_STORAGE_REGION,
        "endpoint": OBJECT_STORAGE_HOST,
        "acl": "private",
        "force_path_style": "true",
    }

    config_dir = os.path.dirname(config_path)
    os.makedirs(config_dir, exist_ok=True)
    # mkstemp creates the file as 0600. Replaced atomically, because every web
    # process runs this at import and a reader must never see half a file.
    fd, tmp_path = tempfile.mkstemp(dir=config_dir, prefix=".rclone.conf.")
    with os.fdopen(fd, "w") as f_handle:
        config.write(f_handle)
    os.replace(tmp_path, config_path)

    log.debug(
        f"Successfully created remote {OBJECT_STORAGE_REMOTE_NAME}",
    )


def get_local_files(local_path: str) -> set:
    """Get set of all files in a local directory (relative paths).

    Args:
        local_path: Path to local directory

    Returns:
        Set of relative file paths
    """
    files = set()
    if not os.path.exists(local_path):
        return files

    for root, _, filenames in os.walk(local_path):
        for filename in filenames:
            # Get full path and make it relative to local_path
            full_path = os.path.join(root, filename)
            rel_path = os.path.relpath(full_path, local_path)
            files.add(rel_path)

    return files


def get_remote_files(remote_path: str) -> set:
    """Get set of all files in a remote directory using rclone ls.

    Args:
        remote_path: Remote path in format "remote:bucket/dirname"

    Returns:
        Set of relative file paths
    """
    ls_params = ["rclone", "ls", remote_path]

    result = run_rclone_with_retry(ls_params, timeout=CONTROL_TIMEOUT)

    # rclone ls returns lines like: "  123456 path/to/file.txt"
    # Extract just the filenames
    files = set()
    for line in result.stdout.strip().split("\n"):
        if line:
            # Split on whitespace and take everything after the size
            parts = line.strip().split(None, 1)
            if len(parts) == 2:
                files.add(parts[1])

    return files


def get_files(
    dirname: str,
    *,
    overwrite: bool = False,
    timeout: float = TRANSFER_TIMEOUT,
) -> None:
    """Download files from object storage to local work directory.

    This copies files from remote to local without deleting local files using rclone
    copy.

    Args:
        dirname: Name of the directory to download
        overwrite: Replace local files that differ from the remote
            (``--checksum``). The default (``--ignore-existing``) only fetches
            files that are missing locally.
        timeout: Seconds before a single download attempt is killed

    Raises:
        ObjectStorageError: If download fails or verification fails
    """
    log.debug(
        f"Downloading files from object storage for {dirname}",
    )
    local_path = JOB_WORK_DIR_TEMPLATE.format(job_id=dirname)
    remote_path = f"{OBJECT_STORAGE_REMOTE_NAME}:{OBJECT_STORAGE_BUCKET}/{dirname}"

    local_files_before = get_local_files(local_path)
    # Download: copy files from remote to local without deleting local files.
    # The default is the loss-free direction: a stale remote copy must not
    # clobber local edits that have not been uploaded yet (measured in
    # COSMONAUT: street-selection edits were silently reverted). A caller whose
    # local directory is meant to mirror the remote — a worker pod picking up a
    # job — asks for it with overwrite=True.
    sync_params = [
        "rclone",
        "copy",
        remote_path,
        local_path,
        "--checksum" if overwrite else "--ignore-existing",
    ]

    result = run_rclone_with_retry(sync_params, timeout=timeout, check_connection=True)
    log.debug(f"Rclone sync result: {result.stdout}")

    # Verify download - check that all remote files are now in local
    # (local may have additional files, which is acceptable with copy)
    local_files_after = get_local_files(local_path)
    remote_files = get_remote_files(remote_path)

    log.debug(
        f"Downloaded {len(local_files_after - local_files_before)} new files to local",
    )

    # Check that all remote files are present locally
    if not remote_files.issubset(local_files_after):
        missing_files = remote_files - local_files_after
        error_msg = (
            f"Download verification failed for {dirname}!\n"
            f"Missing files from remote: {sorted(missing_files)}\n"
            f"Files from local: {sorted(local_files_after)}\n"
            f"Files from remote: {sorted(remote_files)}"
        )
        log.error(error_msg)
        raise ObjectStorageError(error_msg)


def save_files(dirname: str, timeout: float = TRANSFER_TIMEOUT) -> None:
    """Upload files from local work directory to object storage.

    This overwrites remote files with local files using rclone sync.

    Args:
        dirname: Name of the directory to upload
        timeout: Seconds before a single upload attempt is killed

    Raises:
        ObjectStorageError: If upload fails or verification fails
    """
    log.debug(
        f"Uploading files to object storage for {dirname}",
    )
    local_path = JOB_WORK_DIR_TEMPLATE.format(job_id=dirname)
    remote_path = f"{OBJECT_STORAGE_REMOTE_NAME}:{OBJECT_STORAGE_BUCKET}/{dirname}"
    remote_files_before = get_remote_files(remote_path)

    # List local files before upload
    local_files_before = get_local_files(local_path)
    log.debug(
        f"Uploading {len(local_files_before)} files: {sorted(local_files_before)}",
    )

    # Upload: make remote identical to local
    sync_params = [
        "rclone",
        "sync",
        local_path,
        remote_path,
        "--checksum",
    ]

    run_rclone_with_retry(sync_params, timeout=timeout, check_connection=True)

    # Verify upload — compare against pre-sync local listing, not a fresh one,
    # because concurrent workers may create new files between sync and verification.
    remote_files_after = get_remote_files(remote_path)

    log.debug(
        f"Uploaded {len(remote_files_after - remote_files_before)} new files to remote",
    )

    if local_files_before != remote_files_after:
        error_msg = (
            f"Upload verification failed for {dirname}!\n"
            f"Files from local: {sorted(local_files_before)}\n"
            f"Files from remote: {sorted(remote_files_after)}"
        )
        log.error(error_msg)
        raise ObjectStorageError(error_msg)


def upload_files(dirname: str, timeout: float = TRANSFER_TIMEOUT) -> None:
    """Upload files from local work directory to object storage, deleting nothing.

    This copies local files to the remote with ``rclone copy --checksum``: new and
    changed files are uploaded, remote files missing locally stay. Use
    ``save_files`` to make the remote identical to local.

    Args:
        dirname: Name of the directory to upload
        timeout: Seconds before a single upload attempt is killed

    Raises:
        ObjectStorageError: If upload fails or a local file is missing remotely
    """
    log.debug(
        f"Uploading files to object storage for {dirname} without deleting",
    )
    local_path = JOB_WORK_DIR_TEMPLATE.format(job_id=dirname)
    remote_path = f"{OBJECT_STORAGE_REMOTE_NAME}:{OBJECT_STORAGE_BUCKET}/{dirname}"

    # Listed before the upload, not after, because concurrent workers may create
    # new files between the copy and the verification.
    local_files_before = get_local_files(local_path)

    copy_params = [
        "rclone",
        "copy",
        local_path,
        remote_path,
        "--checksum",
    ]
    run_rclone_with_retry(copy_params, timeout=timeout, check_connection=True)

    # Remote may hold more than local (that is the point of copy), so the check
    # is that local is a subset of remote, not equality.
    remote_files = get_remote_files(remote_path)
    if not local_files_before.issubset(remote_files):
        missing_files = local_files_before - remote_files
        error_msg = (
            f"Upload verification failed for {dirname}!\n"
            f"Missing files from local: {sorted(missing_files)}\n"
            f"Files from local: {sorted(local_files_before)}\n"
            f"Files from remote: {sorted(remote_files)}"
        )
        log.error(error_msg)
        raise ObjectStorageError(error_msg)


def delete_file_from_storage(filepath: str, timeout: float = CONTROL_TIMEOUT) -> None:
    """Delete a file from the object storage using rclone.

    Args:
        filepath: Path of the file to delete from object storage
        timeout: Seconds before a single delete attempt is killed
    """
    log.debug(
        f"Deleting file {filepath} from object storage.",
    )

    remote_path = f"{OBJECT_STORAGE_REMOTE_NAME}:{OBJECT_STORAGE_BUCKET}/{filepath}"

    delete_params = [
        "rclone",
        "delete",
        remote_path,
    ]

    run_rclone_with_retry(delete_params, timeout=timeout)

    log.debug(
        f"Successfully deleted file {filepath} from object storage",
    )


def delete_directory_from_storage(
    dirpath: str, timeout: float = TRANSFER_TIMEOUT
) -> None:
    """Delete a directory from the object storage using rclone.

    A directory that does not exist is not an error: the call returns as if it
    had deleted it. A missing bucket still raises. See "Gotchas" in
    docs/conventions/object_storage.md for the measured rclone behaviour.

    Args:
        dirpath: Path of the directory to delete from object storage
        timeout: Seconds before a single purge attempt is killed. The transfer
            budget, not the control one: a purge walks every object below the
            path, so it scales with the job's file count.
    """
    log.debug(
        f"Deleting directory {dirpath} from object storage.",
    )

    remote_path = f"{OBJECT_STORAGE_REMOTE_NAME}:{OBJECT_STORAGE_BUCKET}/{dirpath}"

    purge_params = [
        "rclone",
        "purge",
        remote_path,
    ]

    run_rclone_with_retry(purge_params, timeout=timeout)

    log.debug(
        f"Successfully deleted directory {dirpath} from object storage",
    )


def list_top_level_prefixes() -> set[str]:
    """Return the names of the top-level directories in the bucket.

    One per job id, since every job stores its files below its own id.
    """
    return _list_dirs(f"{OBJECT_STORAGE_REMOTE_NAME}:{OBJECT_STORAGE_BUCKET}")


def _list_dirs(remote_path: str) -> set[str]:
    """Return the names of the directories directly below remote_path."""
    lsf_params = ["rclone", "lsf", "--dirs-only", remote_path]

    result = run_rclone_with_retry(lsf_params, timeout=CONTROL_TIMEOUT)

    # One name per line with a trailing slash ("cosmo-jobs/"), compared whole by
    # callers: a substring test took "cosmo-jobs" for present whenever
    # "cosmo-jobs-old" was.
    return {line.rstrip("/") for line in result.stdout.splitlines()}


def bucket_exists() -> bool:
    """Return whether the configured bucket exists on the object storage."""
    return OBJECT_STORAGE_BUCKET in _list_dirs(f"{OBJECT_STORAGE_REMOTE_NAME}:")


def create_bucket() -> None:
    """Create the object storage bucket if it doesn't already exist."""
    log.debug(f"Creating bucket {OBJECT_STORAGE_BUCKET}")

    if bucket_exists():
        return

    # Create bucket if it doesn't exist
    remote_bucket = f"{OBJECT_STORAGE_REMOTE_NAME}:{OBJECT_STORAGE_BUCKET}"
    bucket_params = [
        "rclone",
        "mkdir",
        remote_bucket,
    ]

    run_rclone_with_retry(bucket_params, timeout=CONTROL_TIMEOUT)


def main():
    """Execute setup_remote or create_bucket based on command line argument."""
    logging.basicConfig(level=logging.DEBUG)

    if len(sys.argv) != 2:
        print("Usage: python object_storage_manager.py [setup_remote|create_bucket]")
        sys.exit(1)

    command = sys.argv[1]

    try:
        if command == "setup_remote":
            setup_remote()
            log.info(
                "Object storage remote setup completed successfully.",
            )
        elif command == "create_bucket":
            create_bucket()
            log.info(
                "Bucket creation completed successfully.",
            )
        else:
            print(f"Unknown command: {command}")
            print(
                "Usage: python object_storage_manager.py [setup_remote|create_bucket]"
            )
            sys.exit(1)
    except ObjectStorageError as e:
        log.error(f"Failed to execute {command}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
