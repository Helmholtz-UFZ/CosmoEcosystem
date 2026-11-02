# A lost job run ends FAILED through a heartbeat sweep and is never retried

A hard kill (OOM, hard time limit, pod restart, admin kill) left the job row RUNNING
forever. When only the prefork child died, Celery acked the message and nothing
happened; when the whole pod died, Redis redelivered the message after the visibility
timeout and the run started again silently, in a loop for a deterministic OOM. We
decided that a job run keeps a heartbeat in its job row, a framework sweep ends runs
whose heartbeat stopped as FAILED with a line in the job log, and nothing is retried:
the run claims its row atomically when it starts (`RUNNING` with no heartbeat yet),
and every delivery that loses the claim is acked and dropped. `task_acks_late` stays
on, `task_reject_on_worker_lost` stays off, and `visibility_timeout` is left at its
default because a redelivery can no longer start a second computation.

## Considered Options

- **Celery means only:** `task_reject_on_worker_lost`, or a handler in the worker main
  process on `WorkerLostError`/`TimeLimitExceeded`, plus inspect. Fast for a dead
  child, but nothing runs when the whole pod dies, inspect cannot tell "not running"
  from "did not answer", and the status would again depend on Celery (ADR 0002).
- **Heartbeat plus Celery handler.** Two mechanisms for one outcome; the sweep alone
  covers all causes within its threshold.
- **Retry N times with an attempt counter.** Another column, and a deterministic OOM
  costs N hours in COSMOPOLITAN. Retry is the user's job reset.
- **Threshold on run duration per app or task spec.** Needed only without a
  heartbeat; with one, a single global threshold fits a 1 h and a 10 min run alike.
- **A new status (LOST, ABORTED).** Every badge, page and status check would need it;
  the job log already says why the run failed.
- **Heartbeat in a framework table or in Redis.** A table makes claim and sweep a join
  instead of one atomic update on `jobs`; Redis loses every heartbeat on a restart and
  would sweep all live runs.

## Consequences

- `JobColumns` gains `heartbeat_at`; every app's `jobs` table must have it before the
  app deploys the framework version that maps it.
- Queueing a run goes through `job_run.mark_queued`; an app with its own job class
  that writes RUNNING itself breaks the claim, and its run is dropped and then swept.
- A deploy that kills a worker pod mid-run fails those runs; users reset them.
- `job_run.run` returns `None` for a dropped delivery; apps skip their post-run work.
- A lost job run sends no end mail.
- Known gap: a message the broker loses leaves its row RUNNING with no heartbeat, and
  the sweep never touches it.
- A database outage longer than the threshold gets live runs swept.
