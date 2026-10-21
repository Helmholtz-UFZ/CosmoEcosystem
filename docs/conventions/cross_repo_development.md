# Cross-Repo Development

The framework and its two consumers, COSMOPOLITAN and COSMONAUT, are developed together. A
framework change is not done when the framework suite is green. It is done when both apps
run on it. This file says how to work across the three repos without committing anything
device-specific.

## Rules

- **Treat every framework change that touches what an app uses as a three-repo change.**
  Plan the app migrations in the same spec, and test them before the framework release, not
  after.
- **Never commit a local path to the framework.** An app's `pyproject.toml` and `uv.lock`
  always pin a released tag (`cosmo-ecosystem @ git+…@vX.Y.Z`). No `[tool.uv.sources]` path
  entry, no absolute path, no relative path that assumes a directory layout.
- **Point an app at a local framework checkout through the environment.** Set
  `COSMO_ECOSYSTEM_PATH` to the checkout and `run_pytest.sh` overlays it:
  1. it runs `uv sync --frozen`, which installs the pinned tag;
  2. it runs `uv pip install --python .venv --editable "$COSMO_ECOSYSTEM_PATH"`;
  3. it exports `UV_NO_SYNC=1` and runs the suite with `uv run --no-sync pytest`.

  The variable lives only in your shell. Nothing in the repo knows where your checkout is.
- **Use `--no-sync` for every command against the overlay.** A plain `uv run` re-syncs to
  the lock file and silently puts the pinned tag back. Use `uv run --no-sync …` for the dev
  server too.
- **Work on app branches in worktrees.** Use `~/git/<repo>.wt/<short-name>`, per
  `~/git/CLAUDE.md`. This is mandatory when the main checkout has uncommitted work.
- **Merge order: framework release first, then the apps.** An app merge request is opened
  against the overlay but lands only after its pin is bumped to the released tag, because
  CI has no overlay.
- **Keep the three suites on their own port slots** so all three can run at once (see
  [testing.md](testing.md#local-port-allocation-across-the-three-repos)).

## Examples

### Do

```bash
export COSMO_ECOSYSTEM_PATH=~/git/cosmo-ecosystem        # or a framework worktree
cd ~/git/cosmopolitan.wt/job-retention
./run_pytest.sh                                          # overlays the checkout
```

### Don't

```toml
# pyproject.toml of an app — leaks the device layout and breaks CI and image builds
[tool.uv.sources]
cosmo-ecosystem = { path = "/home/<user>/git/cosmo-ecosystem", editable = true }
```

## Notes

- **Always pass `--python .venv` to `uv pip install`.** `uv pip` installs into the
  *active* environment, and a shell with `VIRTUAL_ENV` exported (a global venv, an
  activated sibling project) wins over the project's `.venv`. `uv run` and `uv sync`
  ignore a mismatching `VIRTUAL_ENV` with a warning; `uv pip install` does not. On
  2026-10-21 an overlay without the flag installed the framework and its
  dependencies into the user's global venv.
- **`UV_NO_SYNC=1` reaches subprocesses, `--no-sync` does not.** A conftest that
  starts the Celery worker with a plain `uv run celery …` re-syncs to the lock file
  and runs the worker against the pinned tag while the tests run against the
  overlay. The environment variable covers every `uv run` the suite spawns.

- **The overlay is for tests and the dev server only. Images never see it.** The worker
  and prod Dockerfiles install from the lock file, so they always build against the pinned
  tag. A change that only works with the overlay is not released yet.
- **csv_profiler is the exception.** It lives inside the framework repo, so its committed
  `path = "../.."` source points at its own repository, not at a device. It needs no
  overlay.
- **Check what is actually installed when in doubt.** Run
  `uv run --no-sync python -c "import cosmo_ecosystem, sys; print(cosmo_ecosystem.__file__)"`.
  It must print a path inside `COSMO_ECOSYSTEM_PATH`, not inside `.venv/…/site-packages`.
