# Logging Conventions

## Proper Logger Usage

```python
import logging

log = logging.getLogger(__name__)

log.info("message")
log.debug("message")
log.warning("message")
log.error("message", exc_info=True)
```

**DO NOT use:** `extra={"tag": "..."}` - this is a legacy pattern, do not copy.

---

## Log Levels

### DEBUG
Variable values, state transitions, diagnostic details.
```python
log.debug(f"load job with id {job_id}")
log.debug(f"Validating config: {value}")
```

### INFO
Major workflow steps, successful operations.
```python
log.info(f"Starting profiling job for {job_id}")
log.info(f"Save job {self.model.job_id}")
log.info(f"Job {job_id} reset successfully")
```

### WARNING
Degraded states, retries, skipped operations.
```python
log.warning(f"Database OperationalError: {e}")
log.warning(f"Cannot delete - job status is {status}")
log.warning(f"Job already running, ignoring start")
```

### ERROR
Failures, exceptions, critical issues. Use `exc_info=True` for stack traces.
```python
log.error(f"Failed to submit job {job_id}")
log.error(f"Error processing job: {str(e)}", exc_info=True)
```

---

## Best Practices

1. **Always include identifiers** in messages:
   ```python
   log.info(f"Job {job_id} completed")  # Good
   log.info("Job completed")            # Bad - which job?
   ```

2. **Use appropriate level**:
   - Retrying? → WARNING
   - User input invalid? → DEBUG (not ERROR)
   - Operation failed? → ERROR

3. **Include stack traces** for errors:
   ```python
   log.error(f"Error: {e}", exc_info=True)
   ```

---

## Logger Configuration

Configuration is in `src/logger.py`:
- Web/worker: Console + PostgreSQL database logging
- Computation tasks: the worker config, plus the job log (below)
- Third-party package filtering to reduce noise

---

## Job Log

A job's log lives in the `job_logs` table (`cosmo_ecosystem.job_log`), not in a
file in the work dir, so any pod can read it while the run is still going.

A computation task calls `job_run.run`; that call owns the job log:

```python
def start_computation_task(self, job_id):
    return job_run.run(job_id, compute, excluded_packages=EXCLUDED_LOG_PACKAGES)
```

- `run` clears the job log, attaches a `JobLogHandler` to the root logger (and
  lowers the root level to DEBUG) for the run, and detaches it in `finally`.
  Every record logged during the run lands in the job log *and* the worker log.
- Read it with `job_log.read(job_id)`, clear it with `job_log.clear(job_id)`.
- A database error in the handler drops the batch and logs a WARNING to the
  worker log only; the run goes on.

**DO NOT** swap the logging config inside a task (`dictConfig`,
`get_logger_config_computation`, `flush_all_handlers`). It replaces the
worker's handlers, and with them the `JobLogHandler`.

---

## Logs in Test Artifacts

When a Playwright test fails, the `page` fixture in `test/conftest.py` captures all
Python log output (including Dash callbacks, werkzeug requests, and application logs)
into `test/artifacts/<test-dir>/server.log`. This uses a `logging.Handler` that
collects records during the test and writes them on failure.

This means every `log.info(...)`, `log.error(...)`, etc. from your application code
is available for post-mortem debugging without re-running the test.

See [Testing conventions — Test Artifacts](testing.md#test-artifacts) for the full
artifact reference.

---

## Celery and the Root Logger

The worker runs Celery Beat embedded (`--beat`). By default Celery hijacks the
root logger on startup, replacing all handlers with its own stdout-only handler. This
silently drops the PostgreSQL handler.

**Always keep this in `CeleryConfig`:**

```python
worker_hijack_root_logger = False
```

Without it, logs appear in the container stdout (in Celery format) but never reach
the database, and the `/logs` page shows nothing.
