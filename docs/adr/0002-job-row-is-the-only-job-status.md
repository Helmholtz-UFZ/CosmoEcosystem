# The job row is the only source of a job's status

A job's status was known in two places: its job row and the state of the Celery
task that computed it, and COSMONAUT copied the Celery state back into the row on
every poll (SUCCESS → COMPLETED, FAILURE/REVOKED → FAILED). We decided the job row
is the only source. The worker-side job run writes RUNNING, COMPLETED or FAILED to
the row itself and never re-raises a failure of the computation, so a failed run
ends as a *successful* Celery task. Whoever cancels a run writes FAILED to the row
right after revoking it, because a terminated worker writes nothing.

## Considered Options

- **Sync the Celery state back into the row** (COSMONAUT's `get_status`). It covers
  revoked and killed tasks for free, but only while the result backend still holds
  the result (one hour), it makes every poll a broker round trip, and it fights a
  run that records FAILED itself: a swallowed failure is SUCCESS in Celery and would
  be turned into COMPLETED.
- **Re-raise after recording FAILED**, so Celery shows FAILURE too. Rejected because
  the apps' post-run work (notification mails, QR code, `notified_end`) runs after
  the run in the same task and must see both outcomes.

## Consequences

- The Celery state on the worker-management page says nothing about whether a job
  succeeded; read the job row or the job log.
- A worker killed mid-run (OOM, pod restart) leaves the row RUNNING. Detecting that
  is roadmap step #6, not something the Celery state is relied on for.
- A cancel racing a run that just finished can leave FAILED on a finished job, or
  COMPLETED if the worker writes last; both are accepted.
