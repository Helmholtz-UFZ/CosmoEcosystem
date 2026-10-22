"""Job retention: when a job expires, and what deleting a job means."""

import importlib
import logging
import os
import shutil
import sys
import time
import warnings
from dataclasses import dataclass, field
from datetime import date

from cosmo_ecosystem.config import (
    OBJECT_STORAGE_BUCKET,
    WEB_WORK_DIR,
)
from cosmo_ecosystem.constants import DAYS_DELETE_NOT_SUBMITTED, DAYS_DELETE_SUBMITTED
from cosmo_ecosystem.db_manager import DbManager
from cosmo_ecosystem.error_handling import JobCleanupFailed
from cosmo_ecosystem import job_persistence
from cosmo_ecosystem.object_storage_manager import (
    bucket_exists,
    list_top_level_prefixes,
    setup_remote,
)

log = logging.getLogger(__name__)

# Job.__init__ creates the work dir, uploads it and only then writes the row,
# so a brand-new job briefly has a dir and no row. Younger orphans are left
# alone so a cleanup in that window (the dashboard "Clean") cannot remove it.
ORPHAN_DIR_GRACE_SECONDS = 60 * 60


@dataclass
class CleanupSummary:
    """What one cleanup run did."""

    deleted_ids: list[str] = field(default_factory=list)
    kept_ids: list[str] = field(default_factory=list)
    failed_ids: list[str] = field(default_factory=list)
    removed_local_dirs: list[str] = field(default_factory=list)


# delete_job and delete_jobs moved to job_persistence. A module-level
# __getattr__ warns exactly when a consumer reaches for the old names, which a
# plain re-export cannot: it would warn on every import of this module, and
# clean_up_jobs lives here too. Remove it one version after 0.11.
_MOVED_TO_PERSISTENCE = ("delete_job", "delete_jobs")


def __getattr__(name: str):
    if name in _MOVED_TO_PERSISTENCE:
        warnings.warn(
            f"cosmo_ecosystem.job_retention.{name} moved to "
            f"cosmo_ecosystem.job_persistence.{name} and will be removed from "
            "job_retention.",
            DeprecationWarning,
            stacklevel=2,
        )
        return getattr(job_persistence, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def days_to_live(
    start_date: date,
    submitted: bool,
    days_delete_not_submitted: int = DAYS_DELETE_NOT_SUBMITTED,
    days_delete_submitted: int = DAYS_DELETE_SUBMITTED,
) -> int:
    """Return the days left before a job expires; zero or less means expired."""
    days_passed = (date.today() - start_date).days
    if submitted:
        return days_delete_submitted - days_passed
    return days_delete_not_submitted - days_passed


def clean_up_jobs(
    days_delete_not_submitted: int = DAYS_DELETE_NOT_SUBMITTED,
    days_delete_submitted: int = DAYS_DELETE_SUBMITTED,
) -> CleanupSummary:
    """Delete every expired job everywhere and report what was done.

    A job that fails to delete is logged and skipped so the others still go.

    Raises:
        JobCleanupFailed: After the run, if any expired job could not be deleted.
    """
    log.info("Start cleaning up jobs.")
    summary = CleanupSummary()
    expired_ids = []
    for job_id, job_info in DbManager.list_jobs().items():
        remaining = days_to_live(
            job_info["start_date"],
            job_info["submitted"],
            days_delete_not_submitted,
            days_delete_submitted,
        )
        if remaining > 0:
            summary.kept_ids.append(job_id)
        else:
            expired_ids.append(job_id)

    summary.failed_ids = job_persistence.delete_jobs_returning_failures(expired_ids)
    summary.deleted_ids = [
        job_id for job_id in expired_ids if job_id not in summary.failed_ids
    ]

    summary.removed_local_dirs = _remove_orphaned_local_dirs()

    # Every deleted job had its remote prefix removed, so that count is the
    # number of deleted jobs.
    log.info(
        f"Cleanup done: {len(summary.deleted_ids)} deleted with their remote "
        "prefixes, "
        f"{len(summary.kept_ids)} kept, {len(summary.failed_ids)} failed, "
        f"{len(summary.removed_local_dirs)} orphaned local dirs removed."
    )
    if summary.failed_ids:
        raise JobCleanupFailed(summary.failed_ids)
    return summary


def _remove_orphaned_local_dirs() -> list[str]:
    """Remove local work dirs that belong to no job row, from this disk only.

    Never touches object storage: a rowless local dir says nothing about the
    bucket, which another environment's database may share.

    Returns:
        The names of the removed dirs.
    """
    removed = []
    # Listed again, not reused from the expiry pass: rows deleted there are now
    # gone, and rows whose deletion failed are still here and keep their dir.
    job_ids = DbManager.list_jobs().keys()
    cutoff = time.time() - ORPHAN_DIR_GRACE_SECONDS
    try:
        dir_names = os.listdir(WEB_WORK_DIR)
    except FileNotFoundError:
        log.debug(f"No work dir {WEB_WORK_DIR} on this pod yet.")
        return removed
    for dir_name in dir_names:
        dir_path = os.path.join(WEB_WORK_DIR, dir_name)
        if not os.path.isdir(dir_path) or dir_name in job_ids:
            continue
        if os.path.getmtime(dir_path) > cutoff:
            log.debug(f"Keep young orphaned work dir {dir_name}.")
            continue
        log.debug(f"Remove orphaned local work dir {dir_name}.")
        try:
            shutil.rmtree(dir_path)
        except OSError as error:
            # Not a job failure: no row is lost, and the next run tries again.
            log.error(
                f"Could not remove orphaned local work dir {dir_name}: {error}",
                exc_info=True,
            )
            continue
        removed.append(dir_name)
    return removed


def find_orphaned_prefixes() -> list[str]:
    """Return the remote prefixes that have no row in this database, sorted.

    Read-only. An orphan here is only a candidate: a bucket shared with
    another environment holds that environment's jobs too.
    """
    return sorted(list_top_level_prefixes() - DbManager.list_job_ids())


USAGE = "Usage: python -m cosmo_ecosystem.job_retention <module setting DbManager.job_table>"  # noqa: E501


def main(argv: list[str] | None = None):
    """Print the orphaned remote prefixes for manual review; delete nothing.

    Args:
        argv: One module of the app that assigns ``DbManager.job_table`` on
            import (e.g. ``<app>.celery_app``). Defaults to the command
            line arguments.
    """
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) != 1:
        print(USAGE)
        sys.exit(1)
    (job_table_module,) = argv
    # A dynamic import, against the top-level-only rule on purpose: only the
    # operator knows which app module configures the job table.
    importlib.import_module(job_table_module)
    # A shell, unlike a pod, has no rclone remote until something writes it.
    setup_remote()
    # Not created here: the report is read-only, and a missing bucket may just
    # as well be a mistyped OBJECT_STORAGE_BUCKET.
    if not bucket_exists():
        print(
            f"Bucket {OBJECT_STORAGE_BUCKET} does not exist on this object "
            "storage, so there is nothing to report. On a fresh local stack the "
            "app creates it at startup; otherwise check OBJECT_STORAGE_BUCKET."
        )
        sys.exit(1)

    orphans = find_orphaned_prefixes()
    print(
        f"Remote prefixes in bucket {OBJECT_STORAGE_BUCKET} with no row in this "
        f"database: {len(orphans)}"
    )
    for prefix in orphans:
        print(prefix)
    print(
        "Nothing was deleted. If this bucket is shared with another "
        "environment's database, a listed prefix may belong to that database: "
        "run the report against each one and only treat prefixes listed by "
        "every one as orphaned."
    )


if __name__ == "__main__":
    main()
