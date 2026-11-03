"""Tests for the framework's assembly of the one Celery app of a process.

Each test runs a fresh interpreter with a fake domain module on ``COSMO_DOMAIN``:
the app is built once per process, on first access, so a test in this process
would see whichever domain came first. No broker is needed; building the app and
reading its configuration talks to no service.

The assertions are about what the process ends up with (task names, routes,
queues, beat entries), not about how assembly gets there.
"""

import json
import os
import subprocess
import sys
import textwrap

import pytest

from cosmo_ecosystem.celery_config import BaseCeleryConfig

NAME_CLEANUP_TASK = "cosmo_ecosystem.tasks.maintenance_tasks.cleanup"
NAME_TEST_TASK = "cosmo_ecosystem.tasks.test_tasks.long_running_test"
NAME_SWEEP_TASK = "cosmo_ecosystem.tasks.sweep_tasks.sweep_lost_runs"

FAKE_DOMAIN = """
from celery.schedules import crontab

from cosmo_ecosystem.celery_config import BaseCeleryConfig
from cosmo_ecosystem.task_spec import BeatEntry, TaskSpec


def compute(self, job_id):
    return job_id


def refresh(self):
    return "refreshed"


class CeleryConfig(BaseCeleryConfig):
    timezone = "Europe/Berlin"
{config_extra}

celery_config = CeleryConfig
task_specs = [
    TaskSpec(fn=compute, name="fake_domain.compute", queue="crunch", base_task=None),
    TaskSpec(
        fn=refresh,
        name="fake_domain.refresh",
        queue="nightly",
        base_task=None,
        beat=BeatEntry(schedule=crontab(minute=0, hour=4)),
    ),
]
excluded_log_packages = ("noisy_package",)
log_retention_days = 30
"""

# Prints what the assembled app holds, as JSON, from the worker's entry point.
REPORT = """
import json
from cosmo_ecosystem.celery_app import celery
from cosmo_ecosystem.background_job_manager import background_job_manager

print(json.dumps({
    "tasks": sorted(celery.tasks),
    "routes": celery.conf.task_routes,
    "queues": sorted(q.name for q in celery.conf.task_queues),
    "beat": {
        key: {"task": entry["task"], "queue": entry["options"]["queue"]}
        for key, entry in celery.conf.beat_schedule.items()
    },
    "cleanup_schedule": repr(
        celery.conf.beat_schedule["cosmo_ecosystem.tasks.maintenance_tasks.cleanup"][
            "schedule"
        ]
    ),
    "sweep_schedule": repr(
        celery.conf.beat_schedule["cosmo_ecosystem.tasks.sweep_tasks.sweep_lost_runs"][
            "schedule"
        ]
    ),
    "timezone": celery.conf.timezone,
    "manager_wraps_it": background_job_manager.app is celery,
}))
"""


def _run(tmp_path, script, *, domain="fake_domain", config_extra="", domain_extra=""):
    """Run ``script`` in a fresh interpreter with the fake domain importable.

    ``domain_extra`` is appended to the domain module, after its own attributes,
    so it can replace one of them.
    """
    (tmp_path / "fake_domain.py").write_text(
        FAKE_DOMAIN.format(config_extra=textwrap.indent(config_extra, "    "))
        + domain_extra
    )
    env = {**os.environ, "PYTHONPATH": str(tmp_path)}
    env.pop("COSMO_DOMAIN", None)
    if domain is not None:
        env["COSMO_DOMAIN"] = domain
    return subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )


@pytest.fixture
def report(tmp_path):
    """The assembled app of a process whose domain is the fake one."""
    result = _run(tmp_path, REPORT)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_framework_and_domain_tasks_are_registered_by_name(report):
    assert {
        NAME_CLEANUP_TASK,
        NAME_SWEEP_TASK,
        NAME_TEST_TASK,
        "fake_domain.compute",
        "fake_domain.refresh",
    } <= set(report["tasks"])


def test_every_task_is_routed_to_its_queue(report):
    assert report["routes"] == {
        NAME_CLEANUP_TASK: {"queue": "maintenance"},
        NAME_SWEEP_TASK: {"queue": "maintenance"},
        NAME_TEST_TASK: {"queue": "test"},
        "fake_domain.compute": {"queue": "crunch"},
        "fake_domain.refresh": {"queue": "nightly"},
    }


def test_worker_queues_cover_every_routed_queue_and_the_default(report):
    """A worker started without --queues consumes exactly these."""
    assert report["queues"] == ["crunch", "default", "maintenance", "nightly", "test"]


def test_beat_holds_the_framework_and_the_domain_schedules(report):
    assert report["beat"] == {
        NAME_CLEANUP_TASK: {"task": NAME_CLEANUP_TASK, "queue": "maintenance"},
        NAME_SWEEP_TASK: {"task": NAME_SWEEP_TASK, "queue": "maintenance"},
        "fake_domain.refresh": {"task": "fake_domain.refresh", "queue": "nightly"},
    }


def test_the_cleanup_runs_nightly_at_three(report):
    """03:00 every day; Beat reads it in the app's timezone."""
    assert report["cleanup_schedule"] == ("<crontab: 0 3 * * * (m/h/dM/MY/d)>")


def test_the_sweep_runs_every_five_minutes(report):
    """A lost job run shows FAILED at most threshold plus five minutes after it died."""
    assert report["sweep_schedule"] == "<crontab: */5 * * * * (m/h/dM/MY/d)>"


def test_the_base_config_holds_no_schedule_of_its_own():
    """The beat schedule has one source: the task specs."""
    assert "beat_schedule" not in vars(BaseCeleryConfig)


def test_domain_celery_settings_apply(report):
    assert report["timezone"] == "Europe/Berlin"


def test_the_manager_wraps_the_assembled_app(report):
    assert report["manager_wraps_it"]


@pytest.mark.parametrize("setting", ["task_routes", "beat_schedule"])
def test_domain_config_must_not_set_routes_or_schedule(tmp_path, setting):
    """Routes and schedule come from the task specs only."""
    result = _run(tmp_path, REPORT, config_extra=f"{setting} = {{}}")

    assert result.returncode != 0
    assert "DomainCeleryConfigInvalid" in result.stderr
    assert setting in result.stderr


@pytest.mark.parametrize(
    "replacement",
    [
        "class PlainConfig:\n    timezone = 'UTC'\ncelery_config = PlainConfig",
        "celery_config = BaseCeleryConfig()",
    ],
    ids=["class-outside-the-base", "instance-of-the-base"],
)
def test_domain_config_must_subclass_the_base_config(tmp_path, replacement):
    """The framework defaults only reach a domain through the base class."""
    result = _run(tmp_path, REPORT, domain_extra=f"\n{replacement}\n")

    assert result.returncode != 0
    assert "DomainCeleryConfigNotBase" in result.stderr
    assert "BaseCeleryConfig" in result.stderr


def test_unset_cosmo_domain_names_the_variable(tmp_path):
    result = _run(tmp_path, REPORT, domain=None)

    assert result.returncode != 0
    assert "DomainNotConfigured" in result.stderr
    assert "COSMO_DOMAIN" in result.stderr


def test_importing_the_framework_reads_no_domain(tmp_path):
    """Discovery is lazy: an import alone needs no COSMO_DOMAIN."""
    result = _run(
        tmp_path,
        "import cosmo_ecosystem.celery_app, cosmo_ecosystem.background_job_manager",
        domain=None,
    )

    assert result.returncode == 0, result.stderr


# Submits without naming a queue, the way a domain's submissions do, with the
# broker and the result backend replaced: no service is involved. Reports what
# the manager passed to ``send_task`` and which queue the app's routes pick for
# the sent task name.
SUBMISSION = """
import json
from unittest import mock

from celery import Celery

from cosmo_ecosystem.background_job_manager import background_job_manager
from cosmo_ecosystem.celery_app import NAME_TEST_TASK, celery

sent = []


def send_task(name, args=None, **kwargs):
    sent.append((name, kwargs))
    return mock.Mock(id="task-id")


def routed_queue(name):
    return celery.amqp.router.route({}, name)["queue"].name


with (
    mock.patch.object(celery, "send_task", side_effect=send_task),
    mock.patch.object(Celery, "backend", new_callable=mock.PropertyMock),
):
    background_job_manager.submit_job("fake_domain.compute", "job-1")
    background_job_manager.submit_named_job("fake_domain.refresh")
    background_job_manager.submit_test_task()
    background_job_manager.submit_job("fake_domain.compute", "job-2", queue="other")

print(json.dumps({
    "explicit_queue": [kwargs["queue"] if "queue" in kwargs else None for _, kwargs in sent],
    "routed": [routed_queue(name) for name, _ in sent[:3]],
}))
"""


@pytest.fixture
def submission(tmp_path):
    result = _run(tmp_path, SUBMISSION)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_a_submission_without_a_queue_goes_where_the_task_spec_routes_it(submission):
    """Queue comes only from the task spec; nobody passes it at the call site."""
    assert submission["explicit_queue"][:3] == [None, None, None]
    assert submission["routed"] == ["crunch", "nightly", "test"]


def test_an_explicit_queue_still_overrides_the_route(submission):
    assert submission["explicit_queue"][3] == "other"


# Fires worker_process_init as the prefork pool does in each child, before and
# after assembly, and reports whether the root logger mutes the domain's
# excluded package. The PostgreSQL handler is replaced: there is no database
# here, and the test is about which packages the config mutes, not where it
# writes.
WORKER_LOGGING = """
import json
import logging

from celery.signals import worker_process_init

import cosmo_ecosystem.logger


class NoDatabaseHandler(logging.Handler):
    def __init__(self, connection_params):
        super().__init__()

    def emit(self, record):
        pass


cosmo_ecosystem.logger.PostgreSQLHandler = NoDatabaseHandler

import cosmo_ecosystem.background_job_manager  # noqa: E402
import fake_domain  # noqa: E402
from cosmo_ecosystem import celery_app  # noqa: E402


def muted(name):
    record = logging.LogRecord(name, logging.INFO, "x.py", 0, "msg", None, None)
    return not logging.getLogger().filter(record)


worker_process_init.send(sender=None)
before = muted("noisy_package.sub")

celery_app.get_app()
celery_app.get_app()
worker_process_init.send(sender=None)

print(json.dumps({
    "muted_before_assembly": before,
    "muted_after_assembly": muted("noisy_package.sub"),
    "others_pass": not muted("fake_domain"),
    "receivers": len(worker_process_init.receivers),
}))
"""


@pytest.fixture
def worker_logging(tmp_path):
    result = _run(tmp_path, WORKER_LOGGING)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_importing_the_framework_and_domain_configures_no_worker_logging(
    worker_logging,
):
    """No framework import connects worker_process_init behind the app's back."""
    assert not worker_logging["muted_before_assembly"]


def test_worker_processes_mute_the_domains_excluded_packages(worker_logging):
    assert worker_logging["muted_after_assembly"]
    assert worker_logging["others_pass"]


def test_assembly_connects_the_worker_logging_handler_once(worker_logging):
    assert worker_logging["receivers"] == 1
