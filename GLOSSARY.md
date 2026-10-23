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

**Job log**:
The log records written during a job's latest job run, kept with the job and
readable while the run is still going. A new run starts an empty job log.
_Avoid_: Log file, worker log (the worker log is the worker process's own output)
