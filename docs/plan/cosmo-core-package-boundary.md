# cosmo-core — Package-Boundary Specification (v2, adversarially reviewed)

> **Superseded in part:** the Celery and manager parts of this spec (task registration, `BackgroundJobManager` subclassing or mounted methods, per-app Celery apps) are superseded by [ADR 0003](../adr/0003-framework-assembles-the-celery-app.md): the framework assembles the one Celery app from the domain module.

**Created:** 2026-06-29 · **Updated:** 2026-06-30 (name → `cosmo-framework`; home = renamed cosmo-template repo; distribution = git-tag dependency — see "Decisions update" below) · **Status:** design — reviewed (packaging + completeness critiques folded in; ossification pass cut short by a session limit, see verdict) · **Audience:** maintainers of cosmo-template, cosmopolitan, cosmonaut
**Locked context:** D2 = three repos, one shared `cosmo-core` package · D3 = cosmo-template is build-ground + reference domain, **not** the package home
**Design invariant:** every extraction is shaped so **cosmonaut adopts without a breaking change** (additive shim, re-export, or registration helper), and **independent per-repo pins are the structural ossification backstop** (the `dash_form_factory` precedent: cosmopolitan `0.1.8` / template `0.1.9` / cosmonaut `0.1.7` — three different pins, zero lockstep).

This is the deep-dive companion to [`framework-generalization.md`](framework-generalization.md) §5 (Layer C). It was produced by a map → design → adversarial-critique pass; the corrections below are folded in from those critiques.

---

## Decisions update (2026-06-30) — name, home, distribution (SUPERSEDES conflicting text below)

Taken with the maintainer (Louis) on 2026-06-30; overrides the body where it conflicts — notably the package name "cosmo-core", the "own repo, not the template" stance, and B3 framed as a registry gate.

1. **Name = `cosmo-framework`** (dist) / `cosmo_framework` (import). Everywhere the body says "cosmo-core", read **"cosmo-framework"**. Bonus: matches the paper's "COSMO Framework" wording → paper/code consistency.

2. **Home = the cosmo-template repo, RENAMED to `cosmo-framework`.** cosmo-template is **not** a deployed app (CI lint+test only, no `values.yaml`/k8s), so it has no competing release cadence — the §0/§4 "own separate repo, not the template" reasoning does **not** apply to it. Renaming the template repo into the framework repo is the chosen path (preserves git history + these `docs/plan/` docs). The CSV-profiler stays in-repo as the reference example domain.

3. **Repo structure:**
   ```
   cosmo-framework/            (renamed from cosmo-template)
   ├── cosmo_framework/        # the PUBLISHED package (generic modules) — was src/
   ├── examples/csv_profiler/  # reference domain = plugin SCAFFOLD; depends on the package;
   │                           #   NOT in the wheel; CI smoke-test + the paper's 3rd instance
   ├── pyproject.toml          # packages = ["cosmo_framework"]
   └── docs/plan/              # these design docs
   ```

4. **Distribution = the framework is a pinned DEPENDENCY, not a clone-and-own scaffold.** The "start from a repo" model applies **only** to the domain plugin (copy `examples/csv_profiler` as a new app's starting point). The framework itself must be a shared, versioned artifact — otherwise new apps re-fork it and the "one common framework" paper claim becomes false (a story about shared *ancestry*, not shared *code* — the same cosmetic-generality trap as the "Python-only" question). **The distribution model IS the paper-claim decision.** (Exception: if apps were ever meant to modify framework internals themselves, a dependency is wrong — but then "general framework" is hollow and should leave the paper. Layer A/B assume apps *plug in*, not edit the core.)

5. **B3 revised — no package registry strictly required.** Consume the framework via a **`git+https` dependency pinned to a tag** on UFZ GitLab (`codebase.helmholtz.cloud`):
   ```toml
   "cosmo-framework @ git+https://codebase.helmholtz.cloud/.../cosmo-framework@v0.1.0"
   ```
   Auth via `CI_JOB_TOKEN`/SSH; uv locks the commit. This **dissolves the "no private index" blocker** — only git tags are needed. The built-in GitLab Package Registry (PyPI-compatible) is an optional later upgrade for cleaner `==` pins; public PyPI is not used. **B3 changes from "stand up a registry" to "tag releases on the GitLab repo."**

6. **Unchanged & still live:** §1 (membership), §3 (anti-ossification reconciliations), §6 (build order; **B1** DDL/`init.sql` reality + intersection-only `JobTable`; **B2** test-harness), §7 (P1/P2 gate-zero), §9 (first commit). **B1 and B2 remain the live blockers**; B3 is downgraded to "tag releases."

---

## Review verdict & corrections (v2 — these SUPERSEDE any conflicting text in §0–§9 below)

Three adversarial critiques ran (ossification / packaging-feasibility / completeness). Packaging and completeness completed; **the ossification lens was cut off by a session limit before producing findings** — but its two highest-value targets were independently caught by the completeness lens (the `JobTable` schema claim and the `BaseJob.reload_logs` abstract-method mismatch), and the remaining §3 symbol reconciliations (`get_files` default, `handle_error` dispatch, `register_*(app)`) are additive and judged sound. **A dedicated ossification pass is the one remaining gap to close before implementation.**

### Blockers (resolve before any extraction)

**B1 — There is NO migration/DDL system; the core `JobTable` in §2/§3(g) is factually wrong.** Verified: schema ships as hand-written `docker/init.sql` per app (`DROP TABLE … CREATE TABLE …`); there is **no Alembic and no `create_all`** anywhere; the `JobTable` ORM model is a *second, non-authoritative* mirror of that SQL.
- `created_at`/`updated_at` exist in **no** init.sql and **no** ORM — delete them from the core claim.
- The "JSON `config` column is cosmonaut's shape" claim is **false**: cosmonaut's `jobs` table has many typed columns (`email, membership_upload, predictor_upload, submitted, notified_end, stage, status, version, epsg, start_date, celery_task_id`) **plus** a `config JSONB`; cosmopolitan/template have **no** `config` column (they use `input_data JSONB`), and cosmopolitan additionally has `prepared_input`. A single-JSON-column core table fits **none** of the three.
- **Correction:** core `JobTable` = the strict **intersection** of columns present in all three init.sql *and* touched by core CRUD (realistically `job_id (PK), submitted, status, version`, + `start_date` where present). `LogTable` is the only clean lift (identical columns across all three). Treat core `JobTable` as an **ORM mirror only**; the authoritative schema stays per-app `init.sql`. **Add a section** "DDL ownership & the init.sql/ORM double-source": how a core table change propagates to three hand-written `init.sql` files and three **live UFZ Postgres** databases (a `DROP TABLE`/data-migration task, not a code change).

**B2 — Extraction reds all three test suites; the harness is itself an extension point.** Each `test/conftest.py` hardcodes at import time: the app package, the DB-manager class by its *divergent name* (`PostgresManager`/`DbManager`/`DataBaseManager`, called as `.check_existence("test")`), the celery app path, and the queue list. Cosmopolitan imports `ObjectStorageError` from `object_storage_manager`; cosmonaut from `error_handling` (the exact re-export §3(b) leans on). P2's `FLASK_PORT→PORT` rename breaks cosmonaut's conftest. **Correction:** add a "test harness as extension point" subsection enumerating per-phase conftest changes; **every phase's acceptance gate is "all three suites still pass,"** not "cosmopolitan adopts first." Confirm the `PostgresManager as DataBaseManager` alias keeps `check_existence("test")` working.

**B3 — Publishing is a hard gate, and public PyPI is the unlikely answer.** `cosmo-core` is carved from EUPL-1.2 apps with AGPL-3.0-tagged CI, UFZ-internal, and **no private index exists anywhere** (all locks resolve `pypi.org/simple`; zero `tool.uv.sources`). **Correction:** promote Open Decision #1 to a gate-zero blocker. Default-assume a **private GitLab package registry**: spec the uniform uv-index config + lockfile regen (non-pypi `source`) + `CI_JOB_TOKEN` auth across all three repos as explicit prerequisite work. Public PyPI only if Legal clears AGPL/EUPL publication.

### Majors

- **M1 — `cosmo-core`'s own deps must be WIDE RANGES, not `==`.** Consumers pin ranges (`dash>=3.0.4,<4`, `pydantic>=2.12,<3`, …). Core declaring bare/`==` deps risks `uv sync --frozen` conflicts. Core deps = widest intersecting ranges (`dash>=3.0.4,<4`, `pydantic>=2,<3`, `sqlalchemy>=2,<3`, `celery>=5.3,<6`); `==` applies **only** to consumers pinning `cosmo-core` itself. A core minor that raises a dep floor is effectively a downstream MAJOR.
- **M2 — Use `psycopg2`, not `psycopg2-binary`** (all three consumers use source `psycopg2>=2.9.10,<3`; mixing installs two distributions providing the same import). Better: make the DB driver consumer-provided and have core depend only on `sqlalchemy`.
- **M3 — Dev-loop is NOT "verbatim".** Three repos, three mount mechanics: cosmopolitan/cosmonaut PYTHONPATH-prepend (cosmonaut has no `.venv`, installs `--system`), cosmo-template bind-mounts into `.venv/.../site-packages`. Spec **three distinct** `docker-compose.local-core.yml` files; the mount target must be the directory *containing* `cosmo_core` (mount `../cosmo-core:/python_docker/cosmo-core`, `PYTHONPATH=/python_docker/cosmo-core:…`).
- **M4 — `--local-core` won't hot-reload in cosmonaut.** `cosmonaut_app/app.py` hardcodes the Flask `extra_files` watch to `/python_docker/sensor-routing/sensor_routing`. Add a watch hook for `/python_docker/cosmo-core/cosmo_core`; verify cosmopolitan's reloader picks up the out-of-tree mount.
- **M5 — Two-step release collides with `bump_version_for_cluster`.** Scheduled `build-latest-tag` checks out `GIT_LATEST_TAG`, which predates a manual pin bump → a rebuild silently ships the old `cosmo-core`. **Correction:** the pin bump must land on `main` **and be tagged** before any image build; add a CI assertion that the built image's installed `cosmo-core` == the pin.
- **M6 — Import-DAG must be published and CI-enforced (cycle hazard).** Today cosmopolitan defines `ObjectStorageError` in `object_storage` and imports it into `error_handling`; cosmonaut inverts it AND `error_handling` imports `email_service`. Core DAG: `constants`(leaf), `config`(leaf), `error_handling` imports only `constants`+`config` (**no** `object_storage`, **no** email), `object_storage` imports `error_handling`, nothing imports `object_storage` back. `on_unhandled` is a plain `Callable` defined in `error_handling`. Add an import-linter/`tach` contract.
- **M7 — `cosmo_core.constants` vs cosmonaut's `constants` PACKAGE.** Cosmonaut's constants is a package (`constants/html_ids.py`), and the id *names* differ three ways. P1 is not a flat rename: forks **re-export with alias** (`from cosmo_core.constants import ERROR_MODAL_TITLE_ID as ERROR_MODAL_TITLE_SHARED_ID`) so page call-sites don't churn. Quantify the blast radius (grep the divergent id names across pages).
- **M8 — Asset ownership.** Core helpers emit `bi bi-download` + flatly markup, but template loads icons via CDN `external_stylesheets` while cosmopolitan/cosmonaut rely on **local** assets and pass no `external_stylesheets`. A core component renders broken icons where neither is guaranteed. **Correction:** either (a) core is asset-agnostic with a documented hard prerequisite ("consumer must load bootstrap-icons + a Bootstrap theme"), or (b) ship the CSS/font in the wheel via Dash library-assets. State explicitly that clientside JS (`geojson_functions.js`, `chroma.min.js`, leaflet `dashExtensions_default.js`) is **domain**.
- **M9 — `handle_error` is bound at import via `Dash(on_error=handle_error)`.** P1 cannot be a one-shot cutover. Sequence: (1) forks add core-id aliases in their constants, (2) switch their *local* `handle_error` to the aliased names, (3) only then swap the `handle_error` import to core — the same app boot must resolve the ids.

### Minors / open-decision resolutions

- **OD#3 resolved → DROP** `GLOBAL_MEMORY_LIMIT_MB`/`MEMORY_CHECK_INTERVAL`: defined in two repos, referenced nowhere.
- **OD#4 resolved → FREE** `query_logs` rename: every call site passes positionally; the descriptive-name adoption is non-breaking.
- **`BaseJob.reload_logs` must NOT be `@abstractmethod`** — cosmonaut exposes `get_logs`, not `reload_logs`; either agree one name (rename cosmonaut's, internal/non-breaking) or drop log-refresh from the abstract contract. An abstract method one consumer lacks is itself an ossification break.
- **Trim ceremony:** `minio` is tiny pure-Python → consider an unconditional core dep (one identical pin line) instead of the `[s3]` extra; demote the SemVer section to "additive-by-default, bump-on-removal."
- **`dotenv` vs `python-dotenv`:** keep env-file loading consumer-side; core `getenv` is `os.environ`-only, so core declares no dotenv dep.
- **cosmo-template CI (lint+test) cannot catch packaging/runtime breakage** — smoke-test each release against an image-building consumer (cosmopolitan), not only the template.

### Net effect on the recommended first commit (§9)
§9 still holds and gets *stronger*: start with `constants.py` (P1) + `config.py` (P2 env keys) + `error_handling.py` base exceptions + the byte-identical `_truncate_*` — but **add B3 (private-registry setup) as the true first action**, and put **no** `JobTable`/DDL or asset-dependent component in the first commit. `LogTable` is the only DB object safe to include early.

---

## 0. Executive summary

`cosmo-core` is a standalone package (its own git repo + `pyproject.toml` + `uv.lock` + CI + SemVer tags), consumed by all three apps the way `dash_form_factory` already is: one pin line in `[project].dependencies`, resolved through each repo's committed `uv.lock`. Two facts dominate the design:

1. **cosmopolitan ≈ template modulo the import prefix + additive extensions.** It never blocks extraction and is the correct **first consumer**.
2. **cosmonaut is the systematic outlier** (env-var renames, `self.model` Job wrapper, relocated `ObjectStorageError`, `register_*(app)` callbacks, keyword-only ctor, `POSTGRES_NAME`/`DEBUG`/`FLASK_PORT`). **The API must be designed against cosmonaut, not the matching pair**, or cosmonaut can only adopt by breaking.

Two **gate-zero prerequisites** must land before any UI-touching helper or config can be lifted: **(P1) shared HTML-id constant names** and **(P2) env-var standardization**. Both are deployment/internal-rename work, not API breaks. *(v2 adds B3 — private-registry setup — as a third gate-zero item.)*

---

## 1. Module membership table

Verdict legend: **CORE** = lifts to cosmo-core · **DOMAIN** = stays fork-side · **SPLIT** = part lifts, part stays.

| Candidate module | Verdict | What goes to core | What stays domain | Justification |
|---|---|---|---|---|
| `config.py` | **SPLIT** | `getenv(name)` (byte-identical); shared base constants `WEB_WORK_DIR`, `WEB_OUTSIDE_URL`, `JOB_WORK_DIR_TEMPLATE`, `POSTGRES_*`, `OBJECT_STORAGE_*`, `REDIS_*`, `DEBUG`, `PORT` | Fork extras: `TILESERVER_URL`, `EMAIL_*`, `MAINTAINER_EMAIL`, `DAYS_DELETE_*`, `DOCKER_UID/GID`, `GUNICORN`, `get_download_url()` | `getenv` identical; the *constant surface* diverges only via env-var renames (P2). Fork `config.py` imports the core base then appends. |
| `object_storage_manager.py` | **SPLIT** | `check_result`, `run_rclone_with_retry`, `setup_remote`, `get_local_files`, `get_remote_files`, `get_files`, `save_files`, `delete_file_from_storage`, `delete_directory_from_storage`, `create_bucket`, `main`; `get_presigned_download_url` (see M-trim re extra); re-export of `ObjectStorageError` | bucket/remote names come from `config` | template↔cosmopolitan byte-identical; cosmonaut's diverged signatures are all **additive supersets** → adopt cosmonaut's shape with behavior-preserving defaults. |
| `logs_table.py` | **CORE** | `level_badge`, `format_logs_list`, `create_logs_container` | — | template↔cosmopolitan byte-identical; cosmonaut only drops `create_logs_container` (gains an unused helper) and tightens one lookup. |
| `error_handling.py` | **SPLIT** | `_truncate_string`, `_truncate_data` (byte-identical); base exceptions `JobNotFound`, `FileValidationError`, `ObjectStorageError`, `WorkerManagement*`; `handle_error(...)`; `error_modal(...)` factory; `error_responds_dict` base | Fork exceptions (`WrongCeleryTaskId`, `NoMeasurementPointsError`, `MapTileDownloadError`, `Submitted/NotSubmitted/NotFinishedException`, `InvalidJobID`, `JobExists`); the `send_mail` side-effect | truncate helpers are pure; `handle_error` lifts only once UI-id constants align (P1, see M9) and the email side-effect becomes an injected hook. |
| `files_route.py` | **SPLIT** | `_download_href(job_id)`, `create_download_button(job_id, *, button_id, class_name=...)`, optional `make_workdir_route(prefix)` factory | `serve_files(app)` (route surface is a product decision; bound to Job ctor), `DOWNLOAD_ROUTE_TEMPLATE` value | cosmonaut rewrites the route surface (GPX + pictures, 3 routes); only the button/href helpers are liftable once the button id is a parameter (P1). |
| `logger.py` | **CORE** | `PostgreSQLHandler`, `ExcludeSubmodulesFilter` (excluded set as ctor arg), `get_logger_config_computation`, `_build_stream_config`, `get_logger_config_web(debug=None)`, `get_logger_config_worker()` | the per-fork excluded-module additions (passed in, not hardcoded) | handler/filter/builder effectively identical; the three divergences (dead `debug` param, the cosmopolitan `compuation` typo, the excluded-list extension) are resolvable additively. |
| `celery_app.py` | **SPLIT** | `make_celery_app(...)` factory + the `@worker_process_init` worker-logging hook (`configure_worker_logging`) | the task-registration manifest and `NAME_*_TASK` dotted paths | this file is the per-app task manifest by design; core owns only the factory + worker-init hook. |
| `celery_config.py` | **SPLIT** | `_get_redis_port()`, `BaseCeleryConfig` (broker/backend/serialization/worker-tuning + union of safe retry/time-limit + logging-disable fields) | `task_routes`, `beat_schedule` (domain queue names + task paths) | the ~30 shared lines lift; each fork subclasses to set routes/schedule. *(`GLOBAL_MEMORY_LIMIT_MB`/`MEMORY_CHECK_INTERVAL` dropped — dead, see v2.)* |
| `app.py` | **DOMAIN** | `start_beat_scheduler()`; optionally a Dash/Flask `create_app(...)` factory | app composition + callback wiring order + `app.run` extras | app composition is per-product; cosmonaut's init order differs structurally. Core shared callbacks (if any) ship as `register_*(app)`, never import-time `@callback`. |
| `background_job_manager.py` | **SPLIT** | `BaseJobManager` with `get_job_status`, `get_task_result_info`, `get_all_tasks_overview`, `revoke_job`, `submit_test_task`, `submit_cleanup_task`, **generic `submit_job(task_name, job_id, queue, *, track_task_name=False, **opts)`**; `configure_worker_logging` | `submit_computation_job`/`submit_routing_job`/`submit_upload_job`/`submit_update_db_task` thin wrappers; `NAME_*_TASK` constants | infrastructure methods near-identical; the domain `submit_*` wrappers absorb the `job.job_id` vs `job.model.job_id` divergence so the base never touches Job internals. |
| **Job lifecycle** (`job.py` / `cosmonaut_job.py`) | **SPLIT** | abstract `BaseJob` contract: `job_id` accessor + abstract `save`, `delete`, `submit`, `time_to_live` (NOT `reload_logs` — see v2) | the concrete `Job` / `CosmonautJob` (construction, `self.model` vs attribute storage, all domain methods) | construction + storage model are fundamentally different; only the lifecycle *contract* is liftable. **Last to extract.** |
| **DB manager** (`db_manager.py` / `postgres_manager.py`) | **SPLIT** | `SessionScope`, `Base`, `LogTable`+`to_dict`, log queries (`query_logs`, `query_distinct_modules`, `delete_logs_older_than`), `_get_session`, `session_scope()`, and the 6 shared job-CRUD classmethods — exposed as `PostgresManager`; **`JobTable` = strict intersection only (see B1)** | all crns/timeio/geo methods, extra tables, `set_submitted`/`get_stage`, fork `JobTable` columns | class name diverges across all three → core picks `PostgresManager`, forks alias. **`JobTable` is an ORM mirror of per-app `init.sql`, not authoritative (B1).** |

---

## 2. Public API surface

```
cosmo_core/
├── __init__.py            # exports __version__ only; no re-export of submodules
├── config.py
├── constants.py           # shared UI-id constants (gate-zero P1)
├── error_handling.py
├── object_storage.py      # was object_storage_manager.py
├── logs.py                # was logs_table.py
├── logger.py
├── db.py                  # was db_manager.py / postgres_manager.py
├── jobs.py                # BaseJob + BaseJobManager + submit_job
├── celery.py              # make_celery_app + BaseCeleryConfig + configure_worker_logging
└── files.py               # create_download_button + _download_href + make_workdir_route
```

**Import DAG (M6 — must be acyclic, CI-enforced):** `constants`(leaf) · `config`(leaf) · `error_handling` → {`constants`, `config`} only · `object_storage` → `error_handling` · `db` → {`config`} · `logger` → {`config`} · `logs` → {`constants`} · `jobs` → {`db`} · nothing imports `object_storage` back; `error_handling` imports no email/notifier module.

### `cosmo_core.config`
```python
def getenv(name: str) -> str: ...            # raises ValueError on missing; byte-identical to all three
WEB_WORK_DIR: str; WEB_OUTSIDE_URL: str; JOB_WORK_DIR_TEMPLATE: str
POSTGRES_HOST: str; POSTGRES_PORT: str; POSTGRES_USER: str; POSTGRES_PASSWORD: str; POSTGRES_DB: str   # env POSTGRES_DB (P2)
OBJECT_STORAGE_*: str; REDIS_HOST: str; REDIS_PORT: str
DEBUG: bool                                  # from env FLASK_DEBUG == "1" (P2)
PORT: str                                    # from env FLASK_PORT (P2)
```
**NOT exported:** `EMAIL_*`, `TILESERVER_URL`, `MAINTAINER_EMAIL`, retention/docker constants, `get_download_url()` — all domain. Core declares **no** dotenv dep (env-file loading stays consumer-side).

### `cosmo_core.constants` *(gate-zero P1)*
```python
ERROR_MODAL_ID: str
ERROR_MODAL_TITLE_ID: str
ERROR_MODAL_MESSAGE_ID: str
LOADING_OVERLAY_ID: str
LOGS_CONTAINER_ID: str
DOWNLOAD_BUTTON_ID: str
```
Single source of truth for IDs that core components set via `id=`/`set_props`. Forks **alias-import** these (M7): e.g. cosmonaut `constants/html_ids.py` does `from cosmo_core.constants import ERROR_MODAL_TITLE_ID as ERROR_MODAL_TITLE_SHARED_ID` so page call-sites don't churn. **NOT exported:** any page-specific or domain id.

### `cosmo_core.error_handling`
```python
class JobNotFound(Exception): ...
class FileValidationError(Exception): ...
class ObjectStorageError(Exception): ...
class WorkerManagementError(Exception): ...      # + TaskError/WorkerError/RedisError subclasses
def _truncate_string(s, max_len) -> str: ...
def _truncate_data(data, ...) -> ...: ...
error_responds_dict: dict[type[Exception], dict]
def handle_error(error, *, on_unhandled: Callable[[Exception], None] | None = None) -> None: ...
def error_modal(*, modal_id=ERROR_MODAL_ID, title_id=ERROR_MODAL_TITLE_ID, message_id=ERROR_MODAL_MESSAGE_ID, ...): ...
```
**NOT exported / NOT imported:** `send_mail`, `MAINTAINER_EMAIL`, `email_service`, `object_storage` (M6); fork exceptions subclass core bases locally.

### `cosmo_core.object_storage`
```python
from cosmo_core.error_handling import ObjectStorageError   # re-export — old import path keeps working
def run_rclone_with_retry(params, *, timeout=600, check_connection=False): ...   # cosmonaut superset
def get_files(dirname, *, overwrite=True, verify=True): ...     # defaults = template behavior
def save_files(dirname, *, verify=True): ...
# check_result, setup_remote, get_local_files, get_remote_files, delete_*, create_bucket, main
def get_presigned_download_url(object_key, expiry): ...          # minio dep (see v2: likely unconditional)
```

### `cosmo_core.logs`
```python
def level_badge(level: str): ...                  # color_map.get(level, "primary")
def format_logs_list(logs, show_pid=True): ...    # camelCase {"whiteSpace": "pre-wrap"}
def create_logs_container(container_id=LOGS_CONTAINER_ID, *, default_content=..., max_height=...): ...
```

### `cosmo_core.logger`
```python
class PostgreSQLHandler(logging.Handler): ...     # reads config.POSTGRES_DB
class ExcludeSubmodulesFilter(logging.Filter):
    def __init__(self, excluded_modules=(), ...): ...   # forks append their noisy libs
def get_logger_config_computation(log_file_path): ...   # correct spelling
def _build_stream_config(stream, disable_existing_loggers): ...
def get_logger_config_web(debug=None): ...        # param kept for positional compat, ignored
def get_logger_config_worker(): ...
```

### `cosmo_core.db`
```python
class Base(DeclarativeBase): ...
class SessionScope: ...                            # context manager
class LogTable(Base):                              # the one clean lift — identical across all three
    def to_dict(self) -> dict: ...
class JobTable(Base):                              # ORM MIRROR ONLY (B1). Strict intersection:
    job_id: ...  # PK
    submitted: ...
    status: ...
    version: ...
    # start_date where present; NO created_at/updated_at; NO config column in core
class PostgresManager:                             # forks alias: `as DataBaseManager` / `as DbManager`
    @classmethod
    def session_scope(cls): ...
    @classmethod
    def query_logs(cls, date, start_hour, start_minute, end_hour, end_minute, levels, pid=None, excluded_modules=None): ...
    @classmethod
    def query_distinct_modules(cls): ...
    @classmethod
    def delete_logs_older_than(cls, ...): ...
    @classmethod
    def check_existence(cls, job_id): ...
    @classmethod
    def add_entry(cls, ...): ...
    @classmethod
    def update_column(cls, ...): ...
    @classmethod
    def get_job_columns(cls, ...): ...
    @classmethod
    def delete_job(cls, job_id): ...
    @classmethod
    def list_jobs(cls): ...
```
**NOT exported:** crns/timeio/geo methods, `set_submitted`, `get_stage`, fork tables, fork `JobTable` columns.

### `cosmo_core.jobs`
```python
class BaseJob(ABC):
    @property
    @abstractmethod
    def job_id(self) -> str: ...
    @abstractmethod
    def save(self) -> None: ...
    @abstractmethod
    def delete(self) -> None: ...
    @abstractmethod
    def submit(self) -> None: ...
    @abstractmethod
    def time_to_live(self) -> int: ...
    # NB: log-refresh is NOT abstract (cosmonaut has get_logs, template/cosmopolitan reload_logs) — see v2.

class BaseJobManager:
    def get_job_status(self, task_id): ...
    def get_task_result_info(self, task_id): ...
    def get_all_tasks_overview(self): ...
    def revoke_job(self, task_id, terminate=False): ...
    def submit_test_task(self): ...
    def submit_cleanup_task(self): ...
    def submit_job(self, task_name, job_id, queue, *, track_task_name=False, **opts): ...
```
**NOT exported:** `submit_computation_job`/`submit_routing_job`/`submit_upload_job`/`submit_update_db_task` (fork wrappers), `NAME_*_TASK`.

### `cosmo_core.celery`
```python
def make_celery_app(name, config, *, task_modules=()) -> Celery: ...
class BaseCeleryConfig: ...                        # broker/backend/serialization + union of safe defaults; NO task_routes/beat_schedule
def configure_worker_logging(**kwargs) -> None: ...
```

### `cosmo_core.files`
```python
def _download_href(job_id, *, route_template): ...
def create_download_button(job_id, *, button_id=DOWNLOAD_BUTTON_ID, class_name="...", icon=True): ...
def make_workdir_route(prefix: str) -> str: ...
```
**NOT exported:** `serve_files` (domain). **Asset note (M8):** these emit `bi bi-download`/flatly markup — core does NOT ship CSS/fonts; the consumer must load bootstrap-icons + a Bootstrap theme (documented prerequisite), or core ships them via Dash library-assets. Clientside JS is domain.

---

## 3. Anti-ossification reconciliation (the heart)

For each diverged symbol: **core shape** + **cosmonaut's no-break adoption path**, grouped by mechanism.

### (a) Superset keyword-only params with behavior-preserving defaults
- `run_rclone_with_retry(params, *, timeout=600, check_connection=False)` — adopt cosmonaut's superset; defaults reproduce old behavior, so cosmopolitan/template callers unchanged.
- `get_files(dirname, *, overwrite=True, verify=True)` — `overwrite=True` preserves template's always-`--checksum`, `verify=True` keeps remote⊆local verification; cosmonaut passes `overwrite=False, verify=False` for its `--ignore-existing` perf path. Keyword-only = zero positional breakage. *(Flagged for the missing ossification pass: confirm `overwrite=True` exactly reproduces template's current rclone flags.)*
- `save_files(dirname, *, verify=True)` — cosmonaut opts out with `verify=False`.
- `get_logger_config_web(debug=None)` — dead param kept with default; both call styles work.

### (b) Re-export to keep both import paths
- `ObjectStorageError` canonical in `cosmo_core.error_handling`; `cosmo_core.object_storage` re-exports it. Both historical import paths resolve. (Acyclic per M6.)

### (c) Parameterize HTML-id constants / shared `cosmo_core.constants`
- error-modal ids defined once in `cosmo_core.constants`; helpers default to them and accept overrides. Forks alias-import (M7). **Gate-zero P1**; sequenced per M9 because of `Dash(on_error=handle_error)` import-time binding.
- `create_download_button(job_id, *, button_id=DOWNLOAD_BUTTON_ID, ...)` — id is a parameter; cosmonaut passes `button_id=None, icon=False`.

### (d) Injected hooks for fork side-effects
- `handle_error(error, *, on_unhandled=None)` — core stays side-effect-light (log + `set_props`), uses cosmonaut's membership-test dispatch (no `dict.get`). cosmonaut wires `on_unhandled` to its maintainer-email `send_mail`; email stays out of core/cosmopolitan. *(Flagged for the missing ossification pass: confirm membership-dispatch output is byte-identical to the `.get` idiom.)*

### (e) Abstract `BaseJob` + generic `submit_job` so the manager never touches job internals
- `submit_job(task_name, job_id, queue, *, track_task_name=False, **opts)` takes a plain `job_id`. Fork wrappers extract the id (`job.job_id` vs `job.model.job_id`) — the base never sees it. cosmonaut's redis task-name registration = `track_task_name=True`.
- `BaseJob` abstract = `job_id`/`save`/`delete`/`submit`/`time_to_live` (correct spelling). Construction + storage stay fork-side. template/cosmopolitan rename `time_to_life` internally. **Log-refresh is not abstract** (see v2).

### (f) Config / env-var standardization (deployment change, not API break — P2)
- `POSTGRES_DB` (core reads env `POSTGRES_DB`); cosmonaut renames `POSTGRES_NAME → POSTGRES_DB` in `.env`/k8s + `logger.py`.
- `DEBUG` (core reads `FLASK_DEBUG`); cosmonaut renames its env key; exported constant `DEBUG` already identical → no consumer code change.
- `PORT` (core exports `PORT`, env `FLASK_PORT`); cosmonaut switches `app.py`/`get_download_url` from `FLASK_PORT` to `PORT` (one line). **Also updates cosmonaut's conftest (B2).**

### (g) Job/Log schema — CORRECTED (see B1)
- **`LogTable`** lifts cleanly (identical across all three).
- **`JobTable`** is an **ORM mirror only**; core defines the strict **intersection** (`job_id, submitted, status, version`, + `start_date` where present). It changes no live schema; the authoritative DDL stays per-app `init.sql`. There is **no** core `config`/`created_at`/`updated_at` column. Fork-specific columns/tables stay fork-side.
- `query_logs` descriptive time-param names — **free** (all call sites positional, OD#4).
- `PostgresManager` canonical name; forks alias-import.
- `level_badge` tolerant `.get(level, "primary")` (superset of cosmonaut's strict lookup).
- `ExcludeSubmodulesFilter` base list in core; forks append via ctor arg.
- Shared callbacks (if any) as `register_*(app)`, never import-time `@callback`.

> **Structural backstop (the `dash_form_factory` precedent).** Even where a reconciliation is imperfect, independent pins absorb it: a consumer stays on an older `cosmo-core` pin until it adopts — exactly as the three repos already pin `dash-form-factory` at `0.1.8`/`0.1.9`/`0.1.7`. A new core release never force-breaks a lagging consumer's API. *(Caveat M1: this immunizes against core's API churn, not against core raising its own transitive dep floors once a consumer chooses to bump.)*

---

## 4. Packaging mechanics

**Home (D3↔D2 by separating ROLE from HOME):** `cosmo-core` is its **own git repo** with its own `pyproject.toml`/`uv.lock`/CI/SemVer tags, mirroring `dash_form_factory`/`soil-moisture-prediction`/`sensor-routing`. cosmo-template's **role** is the reference *domain consumer* + clean validation ground; it is not the package home (an in-template package could not carry independent tags nor let the three apps pin different versions — the property that prevents ossification).

**Publishing (B3 — gate-zero):** default-assume a **private GitLab package registry** (the code is AGPL/EUPL UFZ-internal and no index exists today). Add the uv index uniformly to all three repos' config, regenerate the three lockfiles so the `cosmo-core` entry carries the non-pypi `source`, and wire `CI_JOB_TOKEN` auth. Public PyPI only if Legal clears publication.

**`cosmo-core/pyproject.toml` (corrected — wide ranges, `psycopg2`, see M1/M2):**
```toml
[project]
name = "cosmo-core"
version = "0.1.0"
requires-python = ">=3.13"
dependencies = [
    "dash>=3.0.4,<4",
    "dash-bootstrap-components",
    "flask",
    "celery>=5.3,<6",
    "redis",
    "sqlalchemy>=2,<3",
    "pydantic>=2,<3",
    "minio",                # see v2: likely unconditional rather than a [s3] extra
    # psycopg2 is consumer-provided (all three pin psycopg2>=2.9.10,<3); core needs only sqlalchemy
]
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
[tool.hatch.build.targets.wheel]
packages = ["cosmo_core"]
```

**Consumer declaration** (exact `==` for cosmo-core itself, one line, locked via `uv.lock`):
```toml
"cosmo-core==0.1.0",     # cosmopolitan (first), cosmo-template (reference), ufz-cosmonaut
```

**Install paths (both resolve a pure-Python wheel):** cosmopolitan/template `uv sync [--no-dev] --frozen`; cosmonaut `uv export --no-hashes | uv pip install --system` (GDAL/`UV_NO_SYNC` irrelevant to a pure-Python dep). Note the install-integrity asymmetry: cosmonaut's `--no-hashes` path is not hash-verified.

**Dev loop (M3/M4 — three distinct overrides, not "verbatim"):** clone the existing `--local-smp`/`--local-sr`/`local_pkg` pattern per repo. Mount `../cosmo-core:/python_docker/cosmo-core` and set `PYTHONPATH=/python_docker/cosmo-core:/python_docker/<app>/` (mount target = the dir *containing* `cosmo_core`); cosmo-template uses its `site-packages` mount style. Add a `--local-core` flag to each `dev_up.sh`. **cosmonaut must add `/python_docker/cosmo-core/cosmo_core` to its `app.py` Flask `extra_files` watch (M4)** or `--local-core` won't hot-reload.

**Release (M5):** two steps — (1) publish `cosmo-core`, (2) bump the `==` pin in the consumer's `pyproject.toml` **and** `uv.lock`. The bump must land on `main` **and be tagged before any image build** (scheduled `build-latest-tag` checks out `GIT_LATEST_TAG`); the `bump_version_for_cluster` automation only edits `values.yaml` image tags, never the lock. Add a CI assertion that the built image's installed `cosmo-core` equals the pin.

---

## 5. Versioning & breaking-change policy

- **Exact `==` pins** in consumers for `cosmo-core` itself; **wide ranges** for cosmo-core's own deps (M1).
- **Additive-by-default:** new keyword-only param with behavior-preserving default / new symbol = MINOR; removing a symbol, changing a default's behavior, a positional break, or raising a transitive dep floor = MAJOR (downstream-breaking).
- **Rollout without lockstep:** publish → bump cosmopolitan first (verify in its real deployed pipeline) → cosmo-template (API-shape gate) → cosmonaut after its P1/P2 alignment. Three different live pins is the normal, healthy state.

---

## 6. Build order + DDL ownership + test harness

**Extraction order** (leaves first; Job contract last — Job classes are domain, only the abstract lifecycle is liftable; the manager depends only on a `job_id` accessor):

| Phase | Modules | Depends on |
|---|---|---|
| **0 — gate-zero** | private registry (B3); `cosmo_core.constants` (P1 ids, alias-import per M7/M9); env-var standardization (P2) | nothing |
| **1 — leaves** | `config`, `error_handling`, `object_storage`, `logs`, `logger`, db **log-layer** (`SessionScope`/`Base`/`LogTable`/log queries) | P1 for UI bits; P2 for config/logger |
| **2 — db job-CRUD** | `PostgresManager` 6 classmethods + intersection-only `JobTable` ORM mirror (B1) | Phase 1 |
| **3 — managers** | `BaseJobManager` + `submit_job`, `configure_worker_logging`, `make_celery_app`, `BaseCeleryConfig` | Phase 2 |
| **4 — last** | abstract `BaseJob` contract | Phase 3 |

**DDL ownership (B1) — new.** Schema = hand-written per-app `docker/init.sql` (`DROP TABLE`/`CREATE TABLE`), no Alembic, no `create_all`; the ORM `JobTable`/`LogTable` are non-authoritative mirrors. **A core table-shape change is a deployment task**: edit each app's `init.sql` + migrate three live UFZ Postgres DBs (`DROP TABLE` + data move), not a Python change. Core therefore owns only the *intersection* shape; anything more requires coordinated per-app DDL. (Adopting a real migration tool — Alembic or `create_all` — is a separate prerequisite project if maintainers want core to own schema evolution.)

**Test harness as extension point (B2) — new.** Each `test/conftest.py` hardcodes the app package, the DB-manager class name (`.check_existence("test")`), the celery app path, and the queue list; cosmopolitan imports `ObjectStorageError` from object-storage, cosmonaut from error-handling. **Every phase's acceptance gate is "all three suites pass."** Per phase, enumerate conftest edits (import-path swaps, `FLASK_PORT→PORT`, `ObjectStorageError` source, `PostgresManager as DataBaseManager` alias). Generalize conftest to read the package/celery/queues from the active config rather than literals.

---

## 7. Gate-zero prerequisites (must land first)

- **B3 — private registry** (publishing). See §4.
- **P1 — HTML-id constant alignment.** Define ids in `cosmo_core.constants`; forks **alias-import** (M7, accounting for cosmonaut's `constants` *package*). Sequenced per **M9**: (1) add core-id aliases, (2) switch local `handle_error` to aliased names, (3) only then swap the `handle_error` import to core (because `Dash(on_error=handle_error)` binds at import).
- **P2 — env-var standardization.** Core standardizes on `POSTGRES_DB`/`FLASK_DEBUG`/`FLASK_PORT` (env) and `POSTGRES_DB`/`DEBUG`/`PORT` (constants). cosmonaut realigns `.env`/k8s + two import sites + its conftest.

---

## 8. Open decisions for maintainers

1. **Private GitLab registry vs public PyPI** (B3) — blocks the first release. If private: uniform uv-index + lockfile regen + CI auth across three repos.
2. **`POSTGRES_DB` cutover** — hard rename in cosmonaut, or a comment-justified `POSTGRES_DB`-then-`POSTGRES_NAME` transition fallback?
3. ~~`GLOBAL_MEMORY_LIMIT_MB`/`MEMORY_CHECK_INTERVAL`~~ — **resolved: DROP** (dead).
4. ~~`query_logs` keyword rename~~ — **resolved: FREE** (all call sites positional).
5. **Core shared callbacks** (navbar/error/reset) as `register_*(app)`, or component-only and leave all wiring to forks?
6. **`create_app(...)` factory in core** — worth it given cosmonaut's divergent init order?
7. **Adopt a migration tool** (Alembic / `create_all`) so core can own schema evolution, or keep per-app `init.sql` authoritative (B1)?
8. **`minio` unconditional vs `[s3]` extra** (trim — one identical pin line favors unconditional).
9. **Convention cleanups to fold in:** cosmonaut's `@classmethod`s naming the first param `self`; the `compuation`/`time_to_life` typos; the dead `debug` param.

---

## 9. Recommended first commit

> **Repo:** new `cosmo-core` · **Scope:** gate-zero + the cleanest leaves, nothing UI-touching, nothing schema-touching.

**True first action: B3** — stand up the private registry (or clear public-PyPI publication) and wire it into all three repos' uv config. Then:

```
cosmo-core/
├── pyproject.toml                 # §4 corrected snippet (wide ranges, psycopg2 consumer-side)
├── uv.lock                        # locked against the chosen (likely private) index
├── README.md                      # consumer pin + the three --local-core dev loops + two-step/tagged release note
├── .gitlab-ci.yml                 # lint + test (+ note: real packaging breakage is caught in cosmopolitan's image build, not here)
└── cosmo_core/
    ├── __init__.py                # __version__
    ├── constants.py               # P1 ids (alias-import in consumers; sequence per M9)
    ├── config.py                  # getenv + shared base constants (P2 env keys)
    └── error_handling.py          # _truncate_* (byte-identical) + base exceptions; NO handle_error/error_modal yet (need P1 wired)
```

**Why:** `getenv`, `_truncate_string`, `_truncate_data`, and the base exceptions are **byte-identical across all three** (zero reconciliation), and `constants.py` unblocks every later UI-touching lift. It proves the registry + pin + `--local-core` dev loop end-to-end on the lowest-risk surface, cosmopolitan first — before any diverged symbol, any DDL, or any asset-dependent component is touched. `LogTable` is the only DB object safe to add early.

---

## Remaining gap before implementation

Run the **dedicated ossification pass** that was cut short (the §3(a)/(d) flags above: `get_files` default flag-equivalence, `handle_error` membership-dispatch output-equivalence, and the `register_*(app)` callback move being non-breaking for template/cosmopolitan). Everything else has been adversarially reviewed.
