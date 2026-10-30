[![DOI](https://zenodo.org/badge/1338235120.svg)](https://doi.org/10.5281/zenodo.21996475)

# Cosmo Ecosystem

The shared **Dash + Celery + PostgreSQL + S3** application framework at the core of
the sister apps [COSMOPOLITAN](https://github.com/Helmholtz-UFZ/Cosmopolitan) and
[COSMONAUT](https://github.com/Helmholtz-UFZ/Cosmonaut). The framework owns the *workflow machinery*: the app
shell, job lifecycle, Celery wiring, object storage, logging, error handling, and the
infra/ops pages, while a **domain** provides *what flows through it* (its config model,
computation, forms, and workflow pages).


> **This is a read-only mirror.** Development happens at
> [codebase.helmholtz.cloud/…/cosmo-ecosystem](https://codebase.helmholtz.cloud/ufz/tb5-smm/met/wg7/cosmo-ecosystem). Issues and merge requests
> belong there. This copy exists so the software has a citable public home,
> anything pushed here is overwritten by the next mirror sync.

> **Formerly `cosmo-suite`** (and before that `cosmo-framework` / `cosmo-template`).
> Renamed in v0.9.0; the old GitLab and GitHub paths redirect here, and the Zenodo
> concept DOI is unchanged.

This repo is the framework's home. It also ships a reference domain,
[`examples/csv_profiler/`](examples/csv_profiler/), a CSV statistical profiler, that
depends on the framework and is the recommended starting point for a new app.

## Repo layout

```
cosmo-ecosystem/
├── cosmo_ecosystem/        # the published package (domain-free), the wheel
├── examples/csv_profiler/  # reference domain: depends on the framework, NOT in the wheel
│   ├── csv_profiler/       # the example's Python package (app, ProfileConfig, pages, …)
│   ├── docker/  docker-compose.yml  dev_up.sh  run_pytest.sh  env_*  # its runtime
│   └── test/               # the integration/e2e suite
├── test/                   # framework-scope tests (html-id enforcement)
├── docs/                   # design docs + conventions
└── pyproject.toml          # name = "cosmo-ecosystem"; wheel packages = ["cosmo_ecosystem"]
```

## Consuming the framework

Apps consume `cosmo-ecosystem` as a **pinned git-tag dependency** (not a clone):

```toml
[project]
dependencies = [
    "cosmo-ecosystem @ git+https://codebase.helmholtz.cloud/.../cosmo-ecosystem@v0.13.0",
]

[tool.hatch.metadata]
allow-direct-references = true
```

Auth uses `CI_JOB_TOKEN` / SSH; `uv` locks the resolved commit. A domain plugs itself
into the framework by injecting four `Job` seams at startup; see the
[config-model contract](docs/conventions/config_model_contract.md).

Two things bite every consumer, and neither announces itself as a framework problem:

- **`[tool.hatch.metadata] allow-direct-references = true` is mandatory.** Without it
  hatchling rejects the `git+https://` pin outright: building the app's own wheel
  fails, not the dependency install.
- **The S3 server for tests comes from the framework too.** Include
  `ci/object-storage.gitlab-ci.yml` at the pinned tag and copy one compose block;
  see [object storage](docs/conventions/object_storage.md).
- **`git` must be installed in the CI image.** `uv export` writes the dependency as a
  `git+https://` URL, so an image build without `git` breaks the next time `uv.lock`
  changes, long after the change that caused it.

### Start a new app

Copy `examples/csv_profiler/` as your starting point, replace the domain pieces
(`ProfileConfig`, `computation_module`, `forms`, workflow pages, computation task), and
point the `cosmo-ecosystem` dependency at a released tag.

### `--local-core` dev loop

To develop the framework and an app together, mount the framework source into the
running containers instead of using the installed copy (see
`examples/csv_profiler/docker-compose.local_pkg.yml`): mount `../../cosmo_ecosystem`
and prepend it to `PYTHONPATH`. The mount target is the directory *containing*
`cosmo_ecosystem`. Within this monorepo the example already resolves the framework from
the local path (`[tool.uv.sources]` in the example's `pyproject.toml`), so
`uv sync` in `examples/csv_profiler/` runs it against the working tree.

### Releasing (two-step, tagged)

1. Publish the framework: bump `version` in `pyproject.toml` and tag it on `main`.
2. Bump the `cosmo-ecosystem` pin in each consumer's `pyproject.toml` **and** `uv.lock`,
   and the `ref:` of its `ci/object-storage.gitlab-ci.yml` include.

**The pin bump must land on `main` and be tagged before any image build**: a scheduled
`build-latest-tag` checks out the latest tag, so an untagged bump would silently ship
the old framework.

## Framework vs domain (Phase 1)

The framework owns the **shell + infra/ops pages** and the job/task machinery; the
**workflow pages** stay domain-side until the Layer-B page/result seam:

| Framework (`cosmo_ecosystem/`)                                    | Domain (`examples/csv_profiler/`)                    |
| ---------------------------------------------------------------- | ---------------------------------------------------- |
| `job.py` (generic `Job` + 3 injected seams), `layouts.py` (shell)| `app.py` (composes shell + wires seams), `forms.py`  |
| `background_job_manager.py`, `celery_app.py`/`celery_config.py`  | `pydantic_models.py` (`ProfileConfig`), `computation_module.py` |
| `config`, `db_manager`, `object_storage_manager`, `logger`, errors | `tasks/computation_tasks.py`, domain constants     |
| pages: `logs`, `job_management`, `worker_management`             | pages: `home`, `input`, `results`, `job_submission`  |

The framework package is kept **domain-free**: a CI gate fails if any CSV-profiler
reference appears under `cosmo_ecosystem/`.

## Running the example

```bash
cd examples/csv_profiler
uv sync                      # framework (editable, local path) + example deps
./dev_up.sh                  # app + worker via docker compose  →  http://localhost:8080
./run_pytest.sh              # starts postgres/object-storage/redis and runs the suite
```

## Testing

- **Framework:** `uv run pytest test/` at the repo root (no services needed); plus
  the `ruff` lint and the domain-free grep gate (`.gitlab-ci.yml`).
- **Example (integration + e2e):** from `examples/csv_profiler/`, `./run_pytest.sh`.

## Conventions & design

See [`docs/conventions/`](docs/conventions/) and the design docs in
[`docs/plan/`](docs/plan/) (`framework-generalization.md`,
`cosmo-core-package-boundary.md`).

Two of those are worth reading **before** wiring an app to the framework, because
what they describe fails silently rather than loudly:

- [What a consumer inherits when it imports a framework
  page](docs/conventions/framework_page_imports.md) — importing a page registers
  callbacks and claims HTML ids in your app's global registry. A collision aborts
  the whole callback registry, and the symptom shows up on an unrelated page.
- [Database schema, `Base`, and who owns the
  DDL](docs/conventions/database_schema.md) — one declarative `Base` per process;
  `JobColumns` supplies the strict column intersection as a mixin, each app
  declares its own concrete `jobs` table from it, not the framework.
