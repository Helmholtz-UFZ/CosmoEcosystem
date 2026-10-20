"""Tests for the ``BaseJob`` contract and the concrete ``Job`` that fulfils it.

The contract is only worth anything if the framework's own job satisfies it: if
the reference implementation cannot, the contract is cut wrong, and finding that
out here is cheaper than finding it out in two apps.
"""

from datetime import date, timedelta

import pytest

from cosmo_ecosystem.base_job import BaseJob
from cosmo_ecosystem.constants import DAYS_DELETE_NOT_SUBMITTED, DAYS_DELETE_SUBMITTED
from cosmo_ecosystem.job import Job

CONTRACT_MEMBERS = ("job_id", "save", "delete", "submit", "time_to_live")


def make_job(*, submitted, days_old):
    """Build a Job without touching the database or object storage.

    ``Job.__init__`` loads from postgres or writes to it; ``time_to_live`` is
    pure arithmetic over two attributes. ``__new__`` skips the constructor so
    the contract can be tested without services.
    """
    job = Job.__new__(Job)
    job.start_date = date.today() - timedelta(days=days_old)
    job.submitted = submitted
    return job


def test_job_implements_the_contract():
    """Job is a BaseJob with nothing left abstract — it can be instantiated."""
    assert issubclass(Job, BaseJob)
    assert Job.__abstractmethods__ == frozenset()


@pytest.mark.parametrize("member", CONTRACT_MEMBERS)
def test_contract_members_are_abstract(member):
    """Each member of the agreed contract is actually enforced, not just documented."""
    assert member in BaseJob.__abstractmethods__


def test_log_refresh_is_not_part_of_the_contract():
    """The apps disagree on its name and no framework code calls it."""
    assert "reload_logs" not in BaseJob.__abstractmethods__
    assert "get_logs" not in BaseJob.__abstractmethods__


def test_job_id_round_trips_through_the_property():
    """The abstract property is satisfied without breaking plain assignment."""
    job = Job.__new__(Job)
    job.job_id = "quiet_amber_otter"

    assert job.job_id == "quiet_amber_otter"
    assert str(job) == "quiet_amber_otter"


def test_time_to_live_counts_down_from_the_submitted_budget():
    """A submitted job lives for DAYS_DELETE_SUBMITTED days."""
    assert make_job(submitted=True, days_old=3).time_to_live() == (
        DAYS_DELETE_SUBMITTED - 3
    )


def test_time_to_live_counts_down_from_the_unsubmitted_budget():
    """An unsubmitted job is cleaned up much sooner."""
    assert make_job(submitted=False, days_old=1).time_to_live() == (
        DAYS_DELETE_NOT_SUBMITTED - 1
    )


def test_misspelled_alias_still_answers():
    """COSMOPOLITAN's six `time_to_life` call sites must not break on v0.5.0."""
    job = make_job(submitted=True, days_old=3)

    with pytest.deprecated_call():
        assert job.time_to_life() == job.time_to_live()
