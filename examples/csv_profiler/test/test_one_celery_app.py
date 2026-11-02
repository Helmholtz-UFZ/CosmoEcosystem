"""Guardrail: a web process holds exactly one Celery app, the framework's.

Runs in a fresh interpreter: Celery keeps every app ever built in a process-wide
registry, and this session builds its own. The app is imported with all framework
pages, as the web server does, so a page or job module that builds a second
instance shows up here.
"""

import json
import os
import subprocess
import sys

NAME_COMPUTATION_TASK = "csv_profiler.tasks.computation_tasks.start_computation"

REPORT = """
import json

from celery import _state

import csv_profiler.app  # imports every framework page
from cosmo_ecosystem.background_job_manager import background_job_manager

apps = list(_state._get_active_apps())
print(json.dumps({
    "count": len(apps),
    "is_managers": apps[0] is background_job_manager.app,
    "routes": background_job_manager.app.conf.task_routes,
}))
"""


def test_web_process_holds_one_celery_app_with_the_domain_routes():
    result = subprocess.run(
        [sys.executable, "-c", REPORT],
        env=dict(os.environ),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])

    assert report["count"] == 1
    assert report["is_managers"]
    # The web process routes the domain task too, not only the worker.
    assert report["routes"][NAME_COMPUTATION_TASK] == {"queue": "computation"}
