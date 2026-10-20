# The Worker Image and the Code Nobody Lints

All three consumers ship a Celery worker as a container image, and all three
put an `object_storage_manager.setup_remote()` call in that image's `CMD`
before the worker starts. That line is the least-tested code in the stack, and
it cost COSMONAUT two weeks of production.

---

## What happened

`docker/worker.Dockerfile` named a module that Slice 1b had deleted. Three
things had to be true at once, and all three were:

1. **The import is a string in a Dockerfile.** No linter reads it, no test
   imports it, and `docker build` does not run `CMD`. The path was wrong from
   the moment of the deletion and the image kept building green.
2. **Neither suite starts the worker through the image.** Both use
   `uv run celery` against the source tree, so every test passed against a
   worker that was never the one being shipped.
3. **The command was chained with `;`.** `python3 … setup_remote` exited
   non-zero with `ModuleNotFoundError`, and the shell went straight on to
   `exec celery`. The worker came up looking healthy, just with no rclone
   remote configured.

The user-visible symptom was "Road network construction failed" — a
computation error message, three layers away from a missing storage config.

---

## The two rules

### 1. Chain the `CMD` with `&&`

```dockerfile
CMD echo "Starting Celery worker..." && \
    python3 /python_docker/<pkg>/<pkg>/object_storage_manager.py setup_remote && \
    exec celery -A <app>.celery_app.celery worker \
        ...
```

`;` turns a failed setup into a silently degraded worker. `&&` turns it into a
container that does not start, which a restart loop and any orchestrator
surface immediately. **This is the actual fix** — the test below only shortens
the time to find the next one.

### 2. Run the setup step in the job that builds the image

The build job already has the image and a runner that can run it. Read the
`CMD` back out of the built image, cut it at the `exec celery` marker, and run
the prefix:

```yaml
worker-image-smoke:
  script:
    - docker build -f docker/worker.Dockerfile -t worker-smoke .
    # `docker run --env-file`, unlike compose, keeps the quotes around a value —
    # strip them so config.py reads ./work_dir and not "./work_dir".
    - tr -d '"' < env_ci > /tmp/smoke.env
    - |
      CMD_STR=$(docker inspect --format '{{index .Config.Cmd 2}}' worker-smoke)
      case "$CMD_STR" in
        *"exec celery"*) ;;
        *) echo "CMD has no 'exec celery' marker — this job cannot find the setup step."; exit 1 ;;
      esac
      docker run --rm --env-file /tmp/smoke.env --entrypoint sh worker-smoke \
        -c "${CMD_STR%%exec celery*} true"
```

**Derive the command, never copy it.** A copy of the `CMD` pasted into the CI
file is a second place to keep in step, and a passing copy says nothing about
the command that actually ships — which is the whole failure being guarded
against, one level up. Verified by mutation: with the path bent in the
Dockerfile the derived form exits 2, the copied form stays green.

`setup_remote()` writes an rclone config file and talks to no service, so this
needs no object storage server. It does need the environment `config.py` reads at
import, and the `rclone` binary, which it asks for the config file's path.

**Catches:** any import path in the `CMD` that no longer resolves.
**Does not catch:** a wrong Celery command behind the marker.
That is the step from undetectable to detectable, not completeness.

---

## Where the job lives

**In the apps, not in `cosmo-ecosystem`.** Two reasons, and the second decides it:

- This repo builds no image in CI and has no runner tags; adding the job would
  mean adding docker-in-docker infrastructure for it alone. The apps already
  build their worker image in CI on a runner that can.
- `examples/csv_profiler`'s worker image is never deployed anywhere. The
  outage was in COSMONAUT's *production* image. A test belongs where the image
  ships, and there it costs almost nothing because it fits inside the existing
  build job instead of needing a new one.

The framework's job is to keep the pattern written down and the `CMD` shaped so
the check is possible — hence the `exec celery` marker and the note in
`examples/csv_profiler/docker/worker.Dockerfile`.

---

## The family this belongs to

Same shape as everything in
[framework page imports](framework_page_imports.md): a name is resolved
somewhere other than where it was written, the wrong resolution is a legal
program, and the symptom surfaces in a different service. The difference is
only that here the name lives in a Dockerfile instead of in Python, which is
what put it outside every tool's reach.
