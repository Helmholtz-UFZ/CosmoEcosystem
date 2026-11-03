"""Helpers for tests that set or read a job row's run state directly.

"Stale" and "alive" are set in SQL relative to the database's now(), never with a
mocked clock: the heartbeat is always written with the database's now().
"""

from sqlalchemy import text

from cosmo_ecosystem import job_log
from cosmo_ecosystem.db_manager import DbManager
from cosmo_ecosystem.job_persistence import load_row


def set_heartbeat(job_id, age="0 seconds"):
    """Set job_id's heartbeat to the database's now() minus age, an SQL interval.

    The default gives the row the heartbeat a claimed, live run has.
    """
    with DbManager.session_scope() as session:
        session.execute(
            text(
                "UPDATE jobs SET heartbeat_at = now() - CAST(:age AS interval) "
                "WHERE job_id = :job_id"
            ),
            {"age": age, "job_id": job_id},
        )


def row_and_log(job_id):
    """Return the job's status, heartbeat and job log: what a drop must keep."""
    row = load_row(job_id)
    return row["status"], row["heartbeat_at"], job_log.read(job_id)


def drop_row(job_id):
    """Delete job_id's row whatever its status: test cleanup, not a framework path.

    ``DbManager.delete_job`` refuses a RUNNING row (ADR 0005), and tests leave
    RUNNING rows behind on purpose.
    """
    with DbManager.session_scope() as session:
        session.execute(
            text("DELETE FROM jobs WHERE job_id = :job_id"), {"job_id": job_id}
        )


def set_row_columns(job_id, **columns):
    """Write columns to job_id's row with raw SQL, run-owned ones included.

    For tests that need a row in a given state. The framework refuses these
    writes outside the named transitions (ADR 0005), so a test that needs a
    status, run id or submitted mark sets it here.
    """
    assignments = ", ".join(f"{name} = :{name}" for name in columns)
    with DbManager.session_scope() as session:
        session.execute(
            text(f"UPDATE jobs SET {assignments} WHERE job_id = :job_id"),
            {**columns, "job_id": job_id},
        )
