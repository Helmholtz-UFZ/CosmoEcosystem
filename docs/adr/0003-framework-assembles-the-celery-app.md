# The framework assembles each process's one Celery app from the domain module

Every web process held two Celery instances: the framework pages used one built from
`BaseCeleryConfig`, the app's own code a second one from the app's `CeleryConfig`,
with a different timezone in COSMOPOLITAN. It only worked because broker-level
inspect and revoke do not check who sends them. We decided that the framework builds
the one Celery app of every process, web, worker and CLI alike, from what the app
declares in its **domain module**, which the environment variable `COSMO_DOMAIN`
names. The app declares its tasks as **task specs** and its domain Celery settings as
a `BaseCeleryConfig` subclass. Routes, queues and the beat schedule are derived from
the specs only; a domain config that sets `task_routes` or `beat_schedule` is
rejected. The worker runs `-A cosmo_ecosystem.celery_app.celery` without `--queues`.

Domain submissions are module functions over the framework's manager, not methods
mounted on it or added by subclassing.

## Considered Options

- **Keep app subclasses of `BackgroundJobManager`** and make the framework pages use
  the app's instance. Fixes the two instances, but leaves `celery_app.py` and
  `background_job_manager.py` as app copies, which is what the paper says they are not.
- **Python entry points for discovery.** No environment plumbing, but invisible, and
  Layer B already chose an env-var dotted-module registry over entry points.
- **A small app-side `worker.py` calling a framework `build()`.** Honest, but it is
  the app's assembly file under another name.
- **Mount `submit_methods()` on the manager** (Layer B's plan). Rejected: it is a
  registration side effect, and the csv_profiler pattern (a module function calling
  `submit_job`) already works without one.

## Consequences

- `COSMO_DOMAIN` must be set in every process; it is set with `ENV` in each app's
  Dockerfiles and in its env and compose files. Unset, the process fails at the first
  Celery access, naming the variable.
- The domain module is imported for its side effects (Job seams, `DbManager.job_table`).
  Layer B can wrap its attributes in a `plugin` object without changing discovery.
- No framework module connects a signal at import; worker logging is connected during
  assembly.
- The cleanup task, its name and its 03:00 schedule belong to the framework; the app
  only supplies its log retention and its timezone.
