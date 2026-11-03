# The Domain Module Contract

An app tells the framework everything it needs to assemble a process in one module,
its **domain module** (`<app>/domain.py`), named by the environment variable
`COSMO_DOMAIN`. The framework builds the one Celery app of every process from it
(ADR 0003). The contract is small, but breaking it fails at import time, often as a
circular import that points away from the cause.

## Rules

- **`COSMO_DOMAIN` is set in every process:** web, worker and CLI. Set it with `ENV`
  in every Dockerfile of the app and in its env and compose files. Unset, the first
  Celery access raises `DomainNotConfigured`.
- **The app package is importable in every process without help from the cwd.**
  Install it (`uv sync` does) or put the repo root on `PYTHONPATH`, as the worker
  images do. `celery -A` adds the cwd to `sys.path` only while it imports the `-A`
  module, `cosmo_ecosystem.celery_app`; the domain module is imported lazily after
  that. A CI image that installs only the dependencies fails at worker start with
  `ModuleNotFoundError: <app>`. The old `-A <app>.celery_app` hid this.
- **The domain module exposes exactly these attributes:**
  - `task_specs`: a list of `TaskSpec`, the app's own tasks only. The framework adds
    its cleanup, its sweep of lost job runs and its test task.
  - `celery_config`: a `BaseCeleryConfig` subclass with domain settings only
    (timezone, time limits), each next to the reason for it.
  - `excluded_log_packages`: a tuple of packages muted in worker logging. The
    assembly connects the `worker_process_init` handler with it; the app connects
    or disconnects no signal ([framework_page_imports.md](framework_page_imports.md), failure 4).
  - `log_retention_days`: how long the framework cleanup keeps log rows.
- **`celery_config` never sets `task_routes` or `beat_schedule`.** Both come from the
  task specs; assembly rejects a config that sets either. It also rejects one that is not a
  `BaseCeleryConfig` subclass (`DomainCeleryConfigNotBase`).
- **The queue is named in the task spec only.** Submissions do not pass `queue=`: the
  assembled `task_routes` send each task name to its spec's queue. `submit_job` and
  `submit_named_job` take `queue` as an optional override for a single call.
- **Every task function takes `self` first.** Every task spec is registered with
  `bind=True`.
- **The domain module wires the Job seams and `DbManager.job_table` on import.** The
  worker never imports `app.py`, so this is the only place they are set for it. The
  web process imports the domain module at the top of `app.py`.
- **Nothing the domain module imports may touch the Celery app or the manager
  singleton at import time.** Assembly imports the domain module, so an import-time
  access would assemble the app while the domain module is still half-imported.
  Reach the manager through its module at call time, never with `from … import`.
- **Domain submissions are module functions** over the framework manager's
  `submit_job` / `submit_named_job`. Do not subclass `BackgroundJobManager` or mount
  methods on it.

## Examples

### Do

```python
# <app>/submissions.py
import cosmo_ecosystem.background_job_manager


def submit_computation_job(job) -> tuple[str | None, bool]:
    # Looked up at call time: binding it at import would assemble the Celery app
    # while <app>.domain, which imports this module, is still half-imported.
    manager = cosmo_ecosystem.background_job_manager.background_job_manager
    # No queue: the task's spec in <app>.domain names it, and the routes follow.
    return manager.submit_job(NAME_COMPUTATION_TASK, job.job_id)
```

### Don't

```python
# <app>/job.py, imported by <app>.domain for the Job seams
from cosmo_ecosystem.background_job_manager import background_job_manager  # assembles now
```

## Notes

- The worker starts as `celery -A cosmo_ecosystem.celery_app.celery worker --beat`,
  without `--queues`: it consumes every queue a task spec names. See
  [celery_beat.md](celery_beat.md) and [worker_image.md](worker_image.md).
- The reference is csv_profiler's `domain.py` and `submissions.py`.
- `job_retention`'s orphan report finds the job table through `COSMO_DOMAIN` too.
- The same family of failure as [framework_page_imports.md](framework_page_imports.md):
  something takes effect at import, somewhere other than where it was written.
- Layer B may later wrap these attributes in a `plugin` object; discovery through
  `COSMO_DOMAIN` stays (`docs/plan/framework-generalization.md`).
