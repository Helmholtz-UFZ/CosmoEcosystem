# Celery Beat and the Web Process

Where the periodic-task scheduler runs, and why `app.py` must never start a thread.
Getting this wrong fails without an error message, so it has no other way to be found
than reading this.

## Rules

- **Celery Beat runs embedded in the Celery worker:** `celery worker --beat`, in the
  worker image's `CMD`. Never in `app.py`, and never in the web container.
- **Exactly one worker pod or container runs `--beat`.** A second replica schedules every
  periodic task twice. If the worker ever has to scale out, move Beat into its own
  deployment with `replicas: 1` instead of dropping `--beat` from a scaled worker.
- **`app.py` starts no threads.** No `Thread`, `Timer`, `ThreadPoolExecutor` or
  `.Beat(...)` outside the `if __name__ == "__main__":` block. Each app has
  `test/test_no_threads_in_app.py`, which reads the source and fails otherwise.
- **`gunicorn --preload` is fine, once the rule above holds.** It imports the app once
  in the master and forks the workers, which is what saves memory.

## What went wrong

Until 2026-09 all three apps started Beat in a daemon thread at the end of `app.py`.
Depending on how Gunicorn was started, this broke one of two ways.

**With `--preload` (cosmonaut prod, every dev image with `GUNICORN=1`): a deadlock.**

1. The master imports `app.py`, and the Beat thread starts initialising Celery.
2. Gunicorn forks its workers during that initialisation. Kombu's `cached_property`
   takes an `RLock` on every read, and the forked child inherits that lock still held
   by a thread that no longer exists.
3. The worker's first `send_task` blocks forever at `kombu/utils/objects.py`,
   `with self.lock:`.
4. Gunicorn kills the worker after `--timeout`, with nothing in the logs.

In cosmonaut prod this showed up as "the road network never loads": the membership
upload stopped right before "Submitted task", and from 2026-08-18 on, 3 of 5 uploads
hung. It looked like it worked because a retry could land on the other worker, and
because a worker re-forked later, while the Beat thread was idle, usually came up clean.

Reproduced locally with `gunicorn --preload -w 2` and a route that submits a task:

- with the thread, every fresh start left at least one of the two workers hung
  (3 of 3 runs);
- without it, none did (5 of 5 runs).

**Without `--preload` (cosmopolitan prod, `-w 4`): duplicated schedules.** Every
Gunicorn worker imports `app.py` and starts its own Beat, so every scheduled task ran
four times. The docs claimed the opposite, because they described `--preload`, which the
production image did not use.

## Examples

### Do

```dockerfile
# docker/worker.Dockerfile
CMD echo "Starting Celery worker..." && \
    python3 -m cosmo_ecosystem.object_storage_manager setup_remote && \
    exec celery -A <app>.celery_app.celery worker \
        --queues=default,... \
        --beat \
        --hostname=worker@%h
```

### Don't

```python
# app.py
beat_thread = Thread(target=lambda: background_job_manager.app.Beat().run(), daemon=True)
beat_thread.start()
```

## Notes

- **Local dev and CI:** compose runs the worker from the same Dockerfile, so Beat runs
  there too. The test suites start their worker without `--beat`, and no test needs the
  schedule.
- **Schedule file:** Beat keeps its state in `beat_schedule_filename`
  (`/tmp/celerybeat-schedule`, set in `BaseCeleryConfig`). A pod restart loses it, which
  only matters for schedules shorter than the restart interval.
- **The smoke test from [worker_image.md](worker_image.md) still works:** it cuts the
  `CMD` at `exec celery`, and `--beat` comes after that.
- **Symptom checklist:** a web action hangs and then fails, no error in the logs, the
  Gunicorn PIDs change about `--timeout` seconds later, and the Celery worker itself
  is healthy. Check for threads in `app.py` before anything else.
