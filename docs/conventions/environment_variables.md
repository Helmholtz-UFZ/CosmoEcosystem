# Environment Variables

All environment variables are centralized in `src/config.py`. They are
loaded via `python-dotenv` and validated at startup with a strict `getenv()`
wrapper that raises `ValueError` on any missing variable.

---

## Environment Files

| File | Purpose |
|------|---------|
| `.env` | Active file read by the app (copied from a variant below by `dev_up.sh`) |
| `env_dev` | Local Docker development |
| `env_test` | Local pytest |

---

## Variable Categories

Grouped by service. The full list lives in `config.env_vars`.

- **Web / App**: `WEB_WORK_DIR`, `FLASK_PORT`, `FLASK_DEBUG`, `WEB_OUTSIDE_URL`
- **PostgreSQL**: `POSTGRES_DB`, `POSTGRES_HOST_NAME`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- **Redis / Celery**: `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB`, `REDIS_PASSWORD`
- **Object Storage (S3)**: `OBJECT_STORAGE_ACCESS_KEY`, `OBJECT_STORAGE_SECRET_KEY`, `OBJECT_STORAGE_HOST`, `OBJECT_STORAGE_BUCKET`, `OBJECT_STORAGE_REMOTE_NAME`

---

## How Config Loading Works

1. `config.py` calls `load_dotenv()` at import time.
2. The custom `getenv()` wrapper calls `os.getenv()` and raises `ValueError` if
   the variable is missing.
3. All values are stored as **module-level constants** — import them from
   `src.config`.
4. The `config.env_vars` list enumerates every required variable. Tests use this
   list to validate completeness across all env files.

**Exception: `COSMO_DOMAIN`.** It is in `config.env_vars`, so `test_env.py` checks that
every env file sets it, but `config.py` has no constant for it. `cosmo_ecosystem/domain.py`
reads it lazily, on first access to the Celery app: `config.py` reads every variable at
import, and importing the framework must not need a domain. See
[domain_module.md](domain_module.md).

---

## Docker

How env vars reach containers (see `docker-compose.yml`):

- **App and worker containers**: `env_file: .env` passes all variables from the
  active `.env` file.
- **Postgres and object storage**: `environment:` block with `${VAR}` interpolation
  maps project variables to the service's expected names (e.g.
  `RUSTFS_ACCESS_KEY: ${OBJECT_STORAGE_ACCESS_KEY}`).
- **Host ports** (`FLASK_HOST_PORT`, `POSTGRES_HOST_PORT`, `REDIS_HOST_PORT`,
  `OBJECT_STORAGE_HOST_PORT`, `OBJECT_STORAGE_CONSOLE_HOST_PORT`): read by compose
  only, never by `config.py`, so they are not in `config.env_vars`.
- **Production Dockerfiles** (`docker/prod.Dockerfile`, `docker/worker.Dockerfile`):
  `COPY env_prod .env` bakes non-secret vars into the image; the CMD sources
  `.env` before starting the process.
- **`DOCKER_UID` / `DOCKER_GID`**: Used in `docker-compose.yml` via
  `user: "${DOCKER_UID}:${DOCKER_GID}"` for file permission mapping. The scripts
  that start the app and worker containers source `set_docker_user.sh`, which
  exports the host user's IDs (rootful Docker) or `0:0` (rootless Docker, where
  container root is the host user). The exported values override the env file's
  `1000`, so the bind-mounted source stays writable on either setup. The env file
  values remain for CI and for `docker compose` run by hand.

---

## Local Package Development

The template includes a skeleton `docker-compose.local_pkg.yml` and a
`--local-computation-module` flag in `dev_up.sh`. These are **non-functional
placeholders** that demonstrate the local package development pattern used by
COSMOPOLITAN and COSMONAUT.

Once you extract your computation module into a separate pip-installable package,
activate this pattern by updating the compose override and removing the error
guard in `dev_up.sh`. See the README for the full extraction path.

---

## Testing & Adding New Variables

`test/test_env.py` validates that every env file contains all required variables.

How it works:
1. Iterates over env files (`env_dev`, `env_test`).
2. For each file: copies it to `.env`, reloads with
   `load_dotenv(override=True)`, then checks every var in `config.env_vars` via
   `getenv()`.

**Adding a new env var — checklist:**

1. Add the variable to both env files (`env_dev`, `env_test`).
2. Add it to the `env_vars` list in `src/config.py`.
3. Add a `getenv()` call and module-level constant in `config.py`.
4. Run `./run_pytest.sh` — `test_env.py` will catch any missing vars.
