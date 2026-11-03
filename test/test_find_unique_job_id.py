"""``find_unique_job_id`` hands out a different name on every call."""

from cosmo_ecosystem import job as job_module


def test_successive_calls_do_not_return_the_same_name(monkeypatch):
    """A fixed seed per call made the first free name come out every time."""
    monkeypatch.setattr(job_module.DbManager, "check_existence", lambda job_id: False)

    ids = {job_module.find_unique_job_id() for _ in range(5)}

    assert len(ids) == 5


def test_a_taken_name_is_skipped(monkeypatch):
    taken = []

    def check_existence(job_id):
        taken.append(job_id)
        return len(taken) == 1

    monkeypatch.setattr(job_module.DbManager, "check_existence", check_existence)

    job_id = job_module.find_unique_job_id()

    assert job_id == taken[-1]
    assert job_id != taken[0]
