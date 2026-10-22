# Testing

## Two suites, two commands

| Suite | Where | How | Services |
|---|---|---|---|
| Framework | `test/` at the repo root | `uv run pytest test/` | none |
| Example (integration + e2e) | `examples/csv_profiler/test/` | `./run_pytest.sh` | postgres, object storage (RustFS), redis, a Celery worker |

Everything below is about the **example** suite unless it says otherwise: it is
the one with services, fixtures and Playwright, and the one that actually
exercises the framework end to end.

The framework suite covers what can be checked without a running stack — static
HTML-id enforcement, the release-version places, and the seams the apps depend
on: `handle_error`'s `on_unhandled` / `error_responses` / `expected_errors`, the
`BaseJob` contract, the `serve_files` job class, the layout wrapper,
`create_header`'s optional id, the navbar-callback registration, and the parts of
`object_storage_manager` that need no store (offline presigning, the rclone config
write, the bucket check). It has no `run_pytest.sh` and needs none.

Two of those are worth naming because they are not tests of behaviour:

- `test_html_id_enforcement.py` and the module-level-`@callback` check in
  `test_layouts.py` parse the source. They catch conventions coming undone,
  which no behavioural test can.
- `test_version.py` checks the four hand-maintained places the release version
  is written against each other — never against a tag, because two of them are
  pin examples already naming the version about to be released. The derived
  places (both `uv.lock`) are covered by `uv lock --check` in the lint jobs.

**It does have a `test/conftest.py`, and that file is load-bearing.**
`cosmo_ecosystem.config` reads its environment at import time and raises for anything
missing, so a test module importing the framework needs those variables to exist
*before* collection. conftest sets placeholder values with `os.environ.setdefault`
— an already-exported variable still wins. Without it the suite cannot even be
collected in CI, where there is no `.env` (it is gitignored). A new framework
env var therefore has to be added there too.

## Critical Rules for Running Tests

**ALWAYS run `./run_pytest.sh --help` before your first test execution in a session.**
The help output is the single source of truth for available flags and usage. Do not
guess flags or invent arguments — only use what `--help` shows.

**NEVER run `pytest` or `uv run pytest` directly.** Always use `./run_pytest.sh`.
The script manages `.env` backup/restore, Docker services, and cleanup. Running
pytest directly will use the wrong `.env`, skip service setup, and leave stale state.

**`--no-services` SKIPS most tests.** It passes `--no-services` to pytest, which
causes `dash_app` and `celery_worker` fixtures to call `pytest.skip()`. All e2e
tests and most module tests will be skipped. Only use it for tests that truly need
no services (`test_env`, `test_html_id_enforcement`).

**Check artifacts before rerunning.** On failure, `test/artifacts/<test-name>/`
contains screenshots, traces, HTML snapshots, server logs, and worker logs. Read
these first — they usually explain the failure without needing another run. Note
that `run_pytest.sh` clears previous artifacts by default (use `--keep-artifacts`
to preserve them across runs).

## Test containers have their own names

`run_pytest.sh` starts its services as compose project `cosmo_ecosystem_test` with
containers `postgres_cosmo_ecosystem_test`, `object_storage_cosmo_ecosystem_test` and
`redis_cosmo_ecosystem_test` (names injected by a temporary override file), and its
cleanup runs `docker compose down -v` on that project only. The dev stack's
`*_cosmo_ecosystem` containers are never stopped or removed by a test run; before this
a suite started while `dev_up.sh` was running deleted the dev containers. The host
ports below still collide with a running dev stack, so stop it first.

## Local port allocation across the three repos

All three stacks used to publish the same host ports, so **no two suites could run at
the same time**. Each repo now has its own slot. Canonical source, do not fork it:
[`docs/plan/local-port-allocation.md`](../plan/local-port-allocation.md).

| | Flask | Postgres | Redis | Object storage | Console |
|---|---|---|---|---|---|
| cosmopolitan | 8080 | 5432 | 6379 | 9000 | 9001 |
| cosmonaut | 8081 | 5433 | 6380 | 9010 | 9011 |
| **csv_profiler** | **8082** | **5434** | **6381** | **9020** | **9021** |

Only `env_test` and `env_dev` carry the shifted values; `env_ci` keeps the defaults,
and every `ports:` mapping in `docker-compose.yml` reads
`${…_HOST_PORT:-<previous value>}`, so with none of the variables set the resolved
mappings are unchanged — CI and production are untouched without editing a line there.

Two rules that follow from it:

- **Host port ≠ app-facing port.** `POSTGRES_PORT`, `REDIS_PORT` and
  `OBJECT_STORAGE_HOST` say where the *app* connects. In `env_dev` the app runs inside
  the compose network and must keep `5432` / `6379` / `object-storage:9000`; in `env_test` the
  suite runs on the host, so there they must match the published ports. Setting a
  service's published port on both sides of a mapping breaks the container, which does
  not listen on the shifted port.
- **A port collision does not look like a collision.** It shows up as setup ERRORs, or
  as e2e tests failing against no server — i.e. as a bug somewhere else entirely. It
  cost two agents two aborted runs each before the cause was found. If service startup
  fails or the app is unreachable, check `docker ps` for a sister stack before reading
  any code.

## Troubleshooting: `ModuleNotFoundError` for a package that is installed

If `run_pytest.sh` dies during collection with something like
`ImportError while loading conftest ... No module named 'redis'`, while
`uv run python -c "import redis"` in the same directory works, the venv's
console scripts are stale.

`.venv/bin/pytest` (like every console script) hardcodes an **absolute**
interpreter path in its shebang. Moving or renaming the repository directory
leaves that path pointing at an interpreter that no longer exists, and
`uv run pytest` then **silently falls through to another `pytest` on `PATH`** —
typically the one in an active `VIRTUAL_ENV` — whose `site-packages` has none of
this project's dependencies. Verified by reproduction: with a dead shebang,
`uv run pytest --version` answered the global venv's `9.0.3` instead of the
project's `8.4.2`.

Note what stays healthy and hides the problem: `uv run python` is fine, because
uv resolves that interpreter itself, so `import redis` works when you check it
by hand. Native binaries like `ruff` are fine too, so lint keeps passing while
tests cannot even collect.

Check and repair:

```bash
head -1 .venv/bin/pytest     # must point into the current repo path
rm -rf .venv && uv sync      # rewrites the shebangs
```

Both venvs need this after a move: the framework root and
`examples/csv_profiler/`.

## Code Rules

- All tests go in `test/` (flat directory, no subdirectories)
- Use constants from `src/constants/html_ids.py` for element IDs in
  Playwright locators — never literal ID strings
- All imports at top level
- When adding a required env var, update `test_env.py`'s checks

## Test Types

### E2E tests (`test_e2e.py`)

- Use Playwright via `pytest-playwright` (`page` fixture)
- App served by `dash_app` fixture (werkzeug make_server in background thread)
- Require all services: Postgres, Redis, object storage, Celery worker
- Test full user workflows through the browser
- Reusable helpers in `test/help_functions_tests.py`

### Module tests (everything else)

Service requirements vary by test:

| Test file | Services needed |
|-----------|----------------|
| `test_computation_module.py` | None (unit test, pandas only) |
| `test_db_manager.py` | Postgres |
| `test_job_retention.py` | Postgres, object storage |
| `test_env.py` | None (reads env files only) |
| `test_html_id_enforcement.py` | None (checks source code only) |

The framework suite at the repo root needs no services at all.

## Fixtures (`conftest.py`)

- `pytest_configure()` verifies all services are reachable before any tests run (gated by `--no-services`)
- `dash_app` (session) — starts the Dash app via werkzeug make_server in a background thread, polls until responsive, shuts down cleanly
- `page` (function) — wraps pytest-playwright's page fixture; captures HTML, console logs, server logs, and worker logs on failure
- `celery_worker` (session) — starts a real Celery worker subprocess with log capture, terminates on teardown
- `logger` — configured logger with suppressed third-party noise

## Artifacts

Playwright artifacts are stored in `test/artifacts/` and include:
- **Screenshots** (`--screenshot only-on-failure`): browser screenshots on test failure
- **Traces** (`--tracing retain-on-failure`): Playwright traces viewable with `npx playwright show-trace`
- **HTML snapshots**: rendered DOM at failure time
- **Console logs**: browser console messages
- **Server logs**: Python server-side logs (callbacks, validation errors, file operations)
- **Worker logs**: Celery worker output

**Which artifact to check first:**

| Failure type | Check first |
|---|---|
| Element not found / timeout | `test-failed-1.png` — is the element on screen? |
| Callback race / stuck overlay | `trace.zip` — step through the action timeline |
| JavaScript error | `console.log` — browser-side errors |
| Unexpected app behavior | `server.log` — Dash callback logs and exceptions |
| Background task failure | `worker.log` — Celery worker output and task traces |
| Layout / rendering issue | `page.html` — inspect the DOM structure |

## CI Pipeline

`.gitlab-ci.yml` runs five jobs. Run all of them locally before pushing — the two
suites alone are not enough: on 2026-10-21 a branch with both suites green still
failed CI twice, once on `domain-free` and once on root (below).

| Job | Locally |
|---|---|
| `framework-lint` | `uv run ruff format --check cosmo_ecosystem test`, `uv run ruff check cosmo_ecosystem test`, `uv lock --check` |
| `domain-free` | `! grep -rnE --include='*.py' 'csv_profiler\|ProfileConfig\|computation_module\|validate_csv\|profile_csv\|CSV_UPLOAD' cosmo_ecosystem/` |
| `framework-test` | `uv run pytest test/` |
| `example-lint` | in `examples/csv_profiler/`: `uv run ruff format --check .`, `uv run ruff check .`, `uv lock --check` |
| `example-test` | in `examples/csv_profiler/`: `./run_pytest.sh` |

`.pre-commit-config.yaml` runs the lint commands of `framework-lint` and `example-lint` (ruff format, ruff check, `uv lock --check`) on commit; install once with `uvx pre-commit install`, check everything with `uvx pre-commit run --all-files`.

`domain-free` is the one that surprises: the framework package must not *mention*
the example domain anywhere in Python, docstrings and comments included. Write
`<app>.celery_app`, not `csv_profiler.celery_app`.

### CI runs the tests as root

The CI image runs as root, and root ignores file permissions. A test that provokes
a failure with `chmod` (a read-only directory `rmtree` cannot empty) passes locally
and fails in CI, because the deletion simply succeeds there. To make removal fail for
every user, replace the directory with a symlink: `shutil.rmtree` refuses a symlink
with `OSError`, as root too, and `os.path.isdir` still reports it as a directory. See
`_make_undeletable` in `examples/csv_profiler/test/test_job_retention.py`.

## Examples

### Do

```python
from playwright.sync_api import expect

from src.constants.html_ids import SOME_BUTTON_ID

def test_something(page, dash_app):
    page.goto(f"http://localhost:{PORT}/")
    page.locator(f"#{SOME_BUTTON_ID}").click()
    expect(page.locator(f"#{SOME_BUTTON_ID}")).to_be_visible()
```

### Don't

```python
def test_something(page, dash_app):
    page.locator("#some_button").click()  # Never use literal ID strings
```

## Notes

- `check_all_errors(page)` in `test/help_functions_tests.py` is the standard post-action verification — checks console errors, JS errors, and broken images
- Use `locator.scroll_into_view_if_needed()` before clicking elements that may be off-screen
