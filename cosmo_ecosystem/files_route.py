"""Serve files from a directory."""

import io
import logging
import os
import zipfile

import dash_bootstrap_components as dbc
from dash import html
from flask import send_file, send_from_directory

from cosmo_ecosystem import job_persistence
from cosmo_ecosystem.constants import DOWNLOAD_BUTTON_SHARED_ID
from cosmo_ecosystem.job import Job

log = logging.getLogger(__name__)

DOWNLOAD_ROUTE_TEMPLATE = "/download/<job_id>.zip"


def _download_href(job_id):
    """Build the download URL for a given job ID."""
    return DOWNLOAD_ROUTE_TEMPLATE.replace("<job_id>", str(job_id))


def create_download_button(job_id, class_name="w-100 mt-2"):
    """Create a download button for a job's work directory."""
    return dbc.Button(
        [html.I(className="bi bi-download me-1"), "Download work_dir"],
        id=DOWNLOAD_BUTTON_SHARED_ID,
        color="primary",
        href=_download_href(job_id),
        external_link=True,
        className=class_name,
    )


def serve_files(app, *, job_class=Job):
    """Serve static files from a directory.

    Args:
        app: The Dash app whose Flask server carries the routes.
        job_class: The job class the routes construct to resolve and validate a
            job id. Defaults to the framework's concrete ``Job``; an app with
            its own job class passes it here instead of keeping a copy of this
            module. Keyword-only with a behaviour-preserving default, so
            existing ``serve_files(app)`` calls are unaffected.

            Beyond the ``BaseJob`` contract these routes need two things from
            the class: it must be constructible as ``job_class(job_id)``,
            raising for an unknown or malformed id, and instances must expose
            ``job_id``. The routes fetch the files themselves, through
            ``job_persistence.work_dir``.
    """

    @app.server.route("/pictures/<job_id>/<path:filename>")
    def serve_file(job_id, filename):
        """Serve pictures."""
        log.debug(f"Serve picture {filename} for {job_id}")
        # Assure that the job exists, then make the files current
        job = job_class(job_id)
        work_dir = job_persistence.work_dir(job.job_id)

        response = send_from_directory(work_dir, filename)

        # Add cache control headers to prevent browser caching
        response.headers["Cache-Control"] = (
            "no-store, no-cache, must-revalidate, max-age=0"
        )
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"

        return response

    @app.server.route(DOWNLOAD_ROUTE_TEMPLATE)
    def download_work_dir(job_id):
        """Download the entire work directory as a zip file.

        Security: job_id is validated via job_class() which calls
        validate_job_id() (format check) and queries the database (existence
        check). The working directory path is taken from the validated job
        object, never from user input.
        """
        log.info(f"Download work dir for {job_id}")
        job = job_class(job_id)
        work_dir = job_persistence.work_dir(job.job_id)

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for root, _dirs, files in os.walk(work_dir):
                for file_name in files:
                    file_path = os.path.join(root, file_name)
                    arcname = os.path.relpath(file_path, work_dir)
                    zip_file.write(file_path, arcname)

        zip_buffer.seek(0)
        return send_file(
            zip_buffer,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"{job_id}.zip",
        )
