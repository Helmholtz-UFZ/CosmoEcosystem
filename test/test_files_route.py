"""Tests for the ``job_class`` seam on ``serve_files``.

``files_route`` used to import the concrete framework ``Job`` and construct it
inside the routes, which is why both apps kept a near-copy of this module rather
than adopt it. The point of these tests is that the routes work against a job
class the framework has never heard of.
"""

import io
import zipfile

import dash
import pytest

from cosmo_ecosystem import job_persistence
from cosmo_ecosystem.files_route import serve_files


class FakeJob:
    """A job the framework knows nothing about, satisfying the route's needs."""

    constructed = []

    def __init__(self, job_id):
        """Record the id the route resolved and expose a working directory."""
        FakeJob.constructed.append(job_id)
        self.job_id = job_id


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A Flask test client for an app whose routes use FakeJob.

    ``work_dir`` is replaced by a stand-in that records the id it was asked to
    fetch and hands back a local dir: the framework suite has no object storage.
    """
    (tmp_path / "result.csv").write_text("column,value\na,1\n")
    FakeJob.constructed = []
    FakeJob.fetched = []

    def fake_work_dir(job_id):
        FakeJob.fetched.append(job_id)
        return str(tmp_path)

    monkeypatch.setattr(job_persistence, "work_dir", fake_work_dir)

    app = dash.Dash(__name__)
    # Dash validates the layout on the first request, whatever the route.
    app.layout = dash.html.Div()
    serve_files(app, job_class=FakeJob)
    return app.server.test_client()


def test_download_route_uses_the_injected_job_class(client):
    """The zip is built from the injected class's working_dir, not the framework Job."""
    response = client.get("/download/quiet_amber_otter.zip")

    assert response.status_code == 200
    assert FakeJob.constructed == ["quiet_amber_otter"]
    assert FakeJob.fetched == ["quiet_amber_otter"]

    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert archive.namelist() == ["result.csv"]


def test_picture_route_serves_from_the_job_working_dir(client):
    """A work dir not named "work_dir" must still resolve.

    The route used to build a relative "work_dir/<job_id>", which
    send_from_directory resolves against app.root_path — the installed app
    package — so any app whose WEB_WORK_DIR points elsewhere got a 404 per image
    and no error anywhere else.
    """
    response = client.get("/pictures/quiet_amber_otter/result.csv")

    assert response.status_code == 200
    assert response.data == b"column,value\na,1\n"
    assert FakeJob.constructed == ["quiet_amber_otter"]
    assert FakeJob.fetched == ["quiet_amber_otter"]
    assert response.headers["Cache-Control"] == (
        "no-store, no-cache, must-revalidate, max-age=0"
    )


def test_picture_route_rejects_traversal(client):
    """The filename is still confined to the job's directory."""
    response = client.get("/pictures/quiet_amber_otter/../../etc/passwd")

    assert response.status_code == 404


def test_default_job_class_keeps_serve_files_call_sites_working():
    """``serve_files(app)`` still binds the framework Job — the seam is additive."""
    app = dash.Dash(__name__)

    serve_files(app)

    routes = {rule.rule for rule in app.server.url_map.iter_rules()}
    assert "/download/<job_id>.zip" in routes
    assert "/pictures/<job_id>/<path:filename>" in routes
