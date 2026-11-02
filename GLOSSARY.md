# Cosmo Ecosystem

The shared web framework beneath COSMOPOLITAN and COSMONAUT: users submit jobs, a
background worker computes them, and the results are kept for a limited time.

## Language

### Jobs

**Job**:
One user submission, identified by its job id, from creation until it expires.
_Avoid_: Submission, run (a job run is one computation of a job), task (a task is
the Celery unit that computes a job)

**Job row**:
A job's record in the app's `jobs` database table.
_Avoid_: Job entry, DB job

**Work dir**:
A job's files on local disk, where code reads and writes them.
_Avoid_: Job dir, job folder, working directory, local storage

**Remote prefix**:
A job's files in the object storage bucket, under a prefix named after its job id.
_Avoid_: Remote dir, bucket folder, storage (unqualified)

**Derived file**:
A job file that can be recomputed entirely from the job's other data, so its
copy on local disk may run ahead of the remote prefix.
_Avoid_: Temp file, intermediate file

**Job persistence**:
Loading, saving and deleting a job's row, work dir and remote prefix as one unit.
_Avoid_: Job storage, sync (unqualified)

**Job run**:
One computation of a job by the worker, from pickup to its final status. A job has
zero or more runs; resetting or changing its input and submitting again starts a
new one.
_Avoid_: Execution, attempt, task

**Job reset**:
Returning a job to PENDING, discarding its results and job log but keeping its
input. Submitting it again starts a new job run.
_Avoid_: Restart, rerun

**Job log**:
The log records written during a job's latest job run, kept with the job and
readable while the run is still going. A new run starts an empty job log.
_Avoid_: Log file, worker log (the worker log is the worker process's own output)

**Heartbeat**:
The sign of life a job run leaves in its job row while it computes. A job run that
has not started yet has none.
_Avoid_: Ping, keepalive, last seen

**Lost job run**:
A job run whose worker died before it could record a final status, recognised by a
heartbeat that has stopped. It ends FAILED and is not retried; a job reset starts a
new run.
_Avoid_: Stuck job, stale job, zombie, orphaned job (orphaned names remote prefixes
without a job row)

**Sweep**:
The periodic framework task that ends every lost job run as FAILED and records why in
its job log.
_Avoid_: Reaper, watchdog, cleanup (the cleanup deletes expired jobs and old logs)

### Processes

**Domain module**:
The one module of an app, named by `COSMO_DOMAIN`, that tells the framework
everything about the domain it needs to assemble a process: its task specs, its
Celery settings, its excluded log packages and its log retention. Importing it also
wires the app's Job seams.
_Avoid_: Plugin (until Layer B exists), wiring module, app config

**Task spec**:
An app's declaration of one Celery task: the function, its task name, its queue, an
optional base class and an optional beat schedule. The framework registers, routes
and schedules the task from this alone.
_Avoid_: Task registration, task manifest
