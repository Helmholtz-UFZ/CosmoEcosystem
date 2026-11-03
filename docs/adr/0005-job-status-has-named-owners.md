# A job row's status changes only through named transitions, and a run writes only while it owns the row

Any code holding a Job object could write the whole job row, status included, and
nothing tied a write to the run or state it was meant for: two submits raced past
the guard and queued two runs, a page loaded earlier saved an old status back over a
newer one, a delete removed a row under a live run, and a run that had outlived a
cancel or a false sweep wrote its final status over the next run. We decided that a
job's status, its submitted mark and its run's columns are written only by named
transitions in the framework's job run lifecycle (queue, reset, cancel, claim,
heartbeat, end, sweep), each one conditional update that reports whether it
applied; that saves never write those columns; that the claim gives the run an
identity (`run_id`) and the run's heartbeat and end write only while the row still
carries it; and that input writes, resets and deletes are conditional on the status
they are allowed from.

## Considered Options

- **A version column with optimistic locking on every save.** Catches every stale
  save, but every caller must handle a conflict, including background tasks, and a
  conflict on a column the caller never meant to change is noise. The real conflicts
  are all on status, which a transition guards more simply.
- **App-level locks (Redis lock, `SELECT … FOR UPDATE` around submit).** The old
  `set_submitted` did lock, but checked the wrong thing; a lock spans the slow work
  dir pull and save, and a lock in Redis is lost on restart. One conditional update
  is atomic without holding anything.
- **A "submitting" status between guard and enqueue.** Closes the gap of a web
  process dying after the guard, at the price of a status every page and the sweep
  must know. The gap is the same as a message the broker loses (ADR 0004); accepted.
- **Keying the job log by run.** Would keep an overtaken run's records out of the
  next run's log; needs a column on the log table and a filter in every reader, for a
  case that needs a run surviving a cancel or a false sweep. Not now.

## Consequences

- `JobColumns` gains `run_id`; every app's `jobs` table must have it before the app
  deploys the framework version that maps it.
- `mark_queued` is the submit guard and runs first; `set_submitted` is gone.
  Queueing is allowed from PENDING and FAILED, reset from PENDING, FAILED and
  COMPLETED, cancel from RUNNING only.
- `RUN_OWNED_COLUMNS` (`heartbeat_at`, `run_id`, `status`, `submitted`) are never
  saved. An app that writes status itself bypasses the transitions and breaks this
  ADR.
- `submitted` means "submitted at least once" and is never cleared.
- `job_run.run` returns `None` for a run that was overtaken, like a dropped delivery:
  its end write applied to nothing, so it reports no status and the caller skips
  its post-run work. A submit whose enqueue fails writes FAILED only while the row
  is still a queued run (`job_run.mark_start_failed`).
- A new row is inserted PENDING and not submitted; saving an existing row skips the
  run-owned columns. Input goes onto an existing row only through
  `job_persistence.update_input` (`Job.save_input`), `WHERE status = 'PENDING'`.
- A RUNNING job cannot be deleted, reset or have its input changed; the cleanup
  skips it and purges job log records without a job row.
- Known gaps: a web process dying between the guard and the enqueue leaves a queued
  run without a message; an overtaken run's job log records still reach the job's
  job log.
