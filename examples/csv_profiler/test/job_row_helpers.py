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
