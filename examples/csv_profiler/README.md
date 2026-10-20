# CSV Profiler — reference domain / example app

A minimal reference application built on the [**Cosmo Ecosystem**](../../README.md):
upload a CSV, run a background statistical-profiling job, and view the results.
It is the canonical example of how to plug a domain into the framework, and the
recommended starting point for a new Cosmo Ecosystem app ("copy this directory").

## How it plugs into the framework

The framework `Job` is generic; this app injects the domain at startup (in both
`csv_profiler/app.py` and `csv_profiler/celery_app.py`):

```python
Job.config_model   = ProfileConfig                        # an UploadJobConfig subclass
Job.file_validator = staticmethod(validate_csv)
Job.submit_handler = staticmethod(submit_computation_job)
```

It provides the domain pieces — `ProfileConfig`, the CSV `computation_module`, the
`forms`, the workflow pages (home / input / results / job_submission), and the
Celery worker entry — while the framework provides the app shell and the infra/ops
pages (logs, job management, worker management). See
[`docs/conventions/config_model_contract.md`](../../docs/conventions/config_model_contract.md).

## Framework dependency

In this monorepo the framework is resolved from the local path (editable) via
`[tool.uv.sources]` in `pyproject.toml`, so the example always runs against the
working tree. A standalone downstream app would instead pin a git tag:

```toml
dependencies = [
    "cosmo-ecosystem @ git+https://codebase.helmholtz.cloud/.../cosmo-ecosystem@v0.4.0",
]
```

**Tagged-release note:** bump the pin on `main` **and tag it** before building any
image — a scheduled image build checks out the latest tag, so an untagged pin bump
would silently ship the old framework.

## Run it

**Prerequisites:** Docker (daemon running) and [uv](https://docs.astral.sh/uv/).
Run everything from `examples/csv_profiler/`.

```bash
uv sync         # install the example + cosmo-ecosystem (editable, local path) into a venv
./dev_up.sh     # build & start app + worker + postgres/object-storage/redis via docker compose
```

Open **http://localhost:8080**, upload a CSV, and watch the profiling job run. Stop
the stack with **Ctrl-C** (it tears the containers down on exit). `./dev_up.sh -d`
enables debug mode (auto-reload on code changes).

### Tests

```bash
./run_pytest.sh   # starts postgres/object-storage/redis, runs the suite, tears everything down
```

The end-to-end tests drive a browser with Playwright. If you hit a
`BrowserType.launch: Executable doesn't exist` error, install the matching browser
once:

```bash
uv run playwright install chromium
```

### `--local-core` dev loop

To iterate on the framework and this app together, mount the framework source into
the running containers instead of using the installed copy (see
`docker-compose.local_pkg.yml`): mount `../../cosmo_ecosystem` and prepend it to
`PYTHONPATH`. The mount target is the directory *containing* `cosmo_ecosystem`.
