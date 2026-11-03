"""The worker management page's formatting of what ``inspect()`` returns."""

import importlib
import sys
from types import SimpleNamespace

import dash
import pytest

PAGE_MODULE = "cosmo_ecosystem.pages.worker_management"


@pytest.fixture(scope="module")
def worker_management():
    """Import the page once; ``register_page`` needs a Dash app to exist.

    The page imports the job manager, whose Celery app needs a domain module this
    suite has none of. The formatters under test never touch the manager, so it is
    stubbed for the import only.
    """
    dash.Dash(__name__, use_pages=True, pages_folder="")
    manager_module = "cosmo_ecosystem.background_job_manager"
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(
            sys.modules,
            manager_module,
            SimpleNamespace(background_job_manager=None),
        )
        module = importlib.import_module(PAGE_MODULE)
    yield module
    sys.modules.pop(PAGE_MODULE)


def test_scheduled_tasks_are_read_from_the_request_celery_nests_them_in(
    worker_management,
):
    """``inspect.scheduled()`` wraps each task: eta and priority outside, the rest in ``request``.

    The shape is celery.worker.control._iter_schedule_requests; ``worker`` is added
    by ``BackgroundJobManager.get_task_overview``.
    """
    scheduled = [
        {
            "eta": "2026-11-03T08:15:30+00:00",
            "priority": 6,
            "request": {
                "id": "4b0e0e1c-0f7c-4d57-9a54-6d1d6d5d3b11",
                "name": "cosmo_ecosystem.tasks.maintenance_tasks.cleanup",
                "args": [],
                "kwargs": {},
                "type": "cosmo_ecosystem.tasks.maintenance_tasks.cleanup",
                "hostname": "celery@worker-1",
                "time_start": None,
                "acknowledged": False,
                "delivery_info": {
                    "exchange": "",
                    "routing_key": "default",
                    "priority": 0,
                    "redelivered": False,
                },
                "worker_pid": None,
            },
            "worker": "celery@worker-1",
        }
    ]

    rows = worker_management.format_scheduled_tasks(scheduled)

    assert rows == [
        {
            "task_id": "4b0e0e1c-0f7c-4d57-9a54-6d1d6d5d3b11",
            "task_name": "cleanup",
            "eta": "2026-11-03 08:15:30",
            "queue": "default",
            "worker": "celery@worker-1",
        }
    ]


def test_reserved_tasks_are_read_from_the_flat_request_info(worker_management):
    """``inspect.reserved()`` returns ``Request.info()`` per task, not nested."""
    reserved = [
        {
            "id": "7c1d5e2a-93c4-4a52-b1de-0c4a6f1d9e10",
            "name": "cosmo_ecosystem.tasks.maintenance_tasks.cleanup",
            "args": [],
            "kwargs": {},
            "type": "cosmo_ecosystem.tasks.maintenance_tasks.cleanup",
            "hostname": "celery@worker-1",
            "time_start": None,
            "acknowledged": False,
            "delivery_info": {
                "exchange": "",
                "routing_key": "maintenance",
                "priority": 0,
                "redelivered": False,
            },
            "worker_pid": None,
            "worker": "celery@worker-1",
        }
    ]

    assert worker_management.format_reserved_tasks(reserved) == [
        {
            "task_id": "7c1d5e2a-93c4-4a52-b1de-0c4a6f1d9e10",
            "task_name": "cleanup",
            "queue": "maintenance",
            "worker": "celery@worker-1",
        }
    ]
