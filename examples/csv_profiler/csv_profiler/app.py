"""Dash app for the CSV profiler example — composes the Cosmo Ecosystem shell.

Imports the domain module, which wires the framework Job seams (config model, file
validator, submit handler, app version) and ``DbManager.job_table`` to the CSV
profiler domain, then builds the multi-page Dash app: the
domain workflow pages (home/input/results/job_submission) are auto-discovered from
this package's ``pages/`` folder, while the framework's infra/ops pages (logs, job
management, worker management) are imported explicitly so they register too.
"""

import logging
import logging.config

import dash_bootstrap_components as dbc
from dash import Dash

import cosmo_ecosystem.pages
from cosmo_ecosystem.config import DEBUG, PORT
from cosmo_ecosystem.error_handling import handle_error
from cosmo_ecosystem.files_route import serve_files
from cosmo_ecosystem.job import Job
from cosmo_ecosystem.layouts import app_layout
from cosmo_ecosystem.logger import get_logger_config_web
from cosmo_ecosystem.object_storage_manager import create_bucket, setup_remote

# The domain module (COSMO_DOMAIN) wires the Job seams and DbManager.job_table on
# import, so it must come before any framework page and before any Job is built.
# The framework imports the same module when it assembles the Celery app.
import csv_profiler.domain  # noqa: F401
from csv_profiler.job_reset import job_reset_components

# A web-only seam, under the same rule: the job management page reads its row
# link at import time and refuses to import without one. Assign the package
# attribute, not a copy.
cosmo_ecosystem.pages.job_link = lambda job_id, row: f"/job-submission/{job_id}"

# Configure logging BEFORE Dash() and any getLogger() calls.
logging.config.dictConfig(get_logger_config_web(DEBUG))
log = logging.getLogger(__name__)
log.debug("Web application logging configured.")

# Initialize the Dash app (domain pages auto-discovered from ./pages/)
app = Dash(
    __name__,
    use_pages=True,
    prevent_initial_callbacks=True,
    suppress_callback_exceptions=True,
    on_error=handle_error,
    external_stylesheets=[dbc.themes.FLATLY, dbc.icons.BOOTSTRAP],
)
server = app.server

# Register the framework's infra/ops pages (they live in the installed package,
# not under this app's pages_folder). register_page requires the app to exist
# first, so these imports run after Dash().
import cosmo_ecosystem.pages.logs  # noqa: E402, F401
import cosmo_ecosystem.pages.job_management  # noqa: E402, F401
import cosmo_ecosystem.pages.worker_management  # noqa: E402, F401

# Set up object storage.
setup_remote()
create_bucket()

# No Celery Beat here: it runs embedded in the worker (docker/worker.Dockerfile).
# Gunicorn with --preload imports this module once and then forks its workers; a
# thread started at import can hold one of Celery's internal locks at that moment,
# and the forked worker then blocks forever on its first task submission. Without
# --preload every worker would start its own Beat instead, and every scheduled task
# would run once per worker. See docs/conventions/celery_beat.md in cosmo-ecosystem.

# Serve files
serve_files(app, job_class=Job)

# Main app layout. app_layout() registers the navbar-collapse callback itself,
# since it is the thing that mounts the navbar; an app building its own navbar
# around the shared id calls layouts.register_navbar_callbacks() instead.
# The input and job-submission pages offer a "Reset job" action, so the shell
# also carries the reset modal and its store; job_reset_components() registers
# their callbacks in the same call.
layout = app_layout()
layout.children += job_reset_components()
app.layout = layout

if __name__ == "__main__":
    app.run(debug=DEBUG, port=PORT, host="0.0.0.0")
