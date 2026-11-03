# Database Schema, `Base`, and Who Owns the DDL

## One `Base` per process

`cosmo_ecosystem.db_manager.Base` is the framework's declarative registry and a
**documented export point**. Every table in a Cosmo Ecosystem process belongs on it:

```python
from cosmo_ecosystem.db_manager import Base

class RouteTable(Base):
    __tablename__ = "routes"
    ...
```

`DbManager` owns the engine and the session factory. An app uses
`DbManager.session_scope()` for its own queries rather than creating a second
engine.

### Why a second `Base` is not a style question

Declaring a second `DeclarativeBase` in the same process creates a second mapper
registry, and in practice a second engine and a second connection pool against
the same database. Both apps ran exactly that through Slice 2: their own `Base`
beside the framework's, each mapping `logs` to `logs` and `jobs` to `jobs`. That
was not laziness — through `v0.5.0` the framework itself declared a concrete
`jobs` table on its own `Base` (see below), which made it impossible for an app
to declare its own `jobs` on the same registry: SQLAlchemy raises
`InvalidRequestError: Table 'jobs' is already defined` the moment a second class
claims that `__tablename__`.

Since `v0.6.0` the framework registers no `jobs` table at all (see
`JobColumns` below), so a second `Base` is unwinding-able app-side. The
framework's part was making that possible; doing it is still up to each app.

---

## `JobColumns`: the framework supplies columns, the app supplies the table

Through `v0.5.0` `cosmo_ecosystem.db_manager.JobTable` was a concrete class mapped
directly onto the framework's `Base`. Importing any framework module that
touched jobs — `cosmo_ecosystem.job`, `cosmo_ecosystem.files_route` (its default
`job_class=Job` pulls `cosmo_ecosystem.job` in) — registered a `jobs` table on
`Base.metadata`, and no app could then declare its own.

`v0.6.0` replaces it with `JobColumns`, an unmapped mixin:

```python
class JobColumns:
    job_id = Column(String, primary_key=True)
    start_date = Column(Date)
    submitted = Column(Boolean)
    notified_end = Column(Boolean)
    status = Column(String)
    version = Column(String)
    heartbeat_at = Column(DateTime(timezone=True))
    run_id = Column(UUID(as_uuid=True))
```

Each app declares its own concrete class from it, on the framework `Base`,
alongside whatever extra columns its own `jobs` table carries:

```python
from cosmo_ecosystem.db_manager import Base, JobColumns

class JobTable(JobColumns, Base):
    __tablename__ = "jobs"

    input_data = Column(JSON)
```

and points `DbManager` at it:

```python
DbManager.job_table = JobTable
```

**The assignment trap:** it must land on `DbManager` itself, never on a
subclass. Framework pages call `DbManager.list_jobs()` directly, so inside that
call `cls` is always the base class. `PostgresManager.job_table = JobTable`
configures the app's own call sites and leaves every framework page unconfigured
— the same failure shape as the three in
[framework_page_imports.md](framework_page_imports.md). Calling a job method
before the assignment raises `JobTableNotConfigured`, not an `AttributeError`.

The authoritative DDL still lives in **each app's own `init.sql`** — `JobColumns`
only fixes the columns every app is measured to have, not the table.

### The intersection

Measured across COSMOPOLITAN, COSMONAUT and csv_profiler's `init.sql` on
2026-08-21 — the first time the comparison included all three, not just
COSMOPOLITAN and csv_profiler (which descends from it and so proves nothing
about a third schema):

```
job_id, start_date, submitted, notified_end, status, version
```

`input_data` and `logs` are **not** in the intersection: COSMONAUT's `jobs` table
has neither. (`logs` is on its way out anyway: the job log lives in `job_logs`,
see below.) The `v0.5.0` cut had included them, measured only against
COSMOPOLITAN and csv_profiler, and broke the first time COSMONAUT tried to
declare a job table against it.

Plus one column that is not measured but required: **`heartbeat_at`**
(`TIMESTAMPTZ`, nullable, no default), added in `v0.15.0` for lost job runs
([ADR 0004](../adr/0004-lost-job-runs-are-swept-not-retried.md)). The framework's
job run writes it, always with the database's `now()`:

- `NULL`: the run is queued and no worker has claimed it.
- set: a worker claimed the run (`job_run.run`'s first write) and refreshes it every
  60 s while it computes. The sweep fails a RUNNING row whose heartbeat is older
  than 10 minutes.

And a second one: **`run_id`** (`UUID`, nullable, no default), added for run
ownership ([ADR 0005](../adr/0005-job-status-has-named-owners.md)). It is the
identity of the job run that holds the row:

- `NULL`: the row is queued, reset, or never ran.
- set: the claim wrote a fresh UUID. The run's heartbeat and final status are
  written only `WHERE run_id` is still its own; queueing and a reset clear it.

What stays app-side, and why:

| Column | Where | Why it is not in the intersection |
| --- | --- | --- |
| `input_data` | COSMOPOLITAN, csv_profiler `init.sql` | COSMONAUT's `jobs` table has none |
| `logs` | COSMOPOLITAN `init.sql`, until its migration drops it | held the log file's text; the job log is in `job_logs` now. csv_profiler dropped it |
| `prepared_input` | COSMOPOLITAN | app-specific stage tracking |
| `email` | COSMOPOLITAN `init.sql` | in the DDL only; never read or written, no ORM mapping |
| `celery_task_id` | COSMOPOLITAN `init.sql` | in the DDL only; the app's `celery_task_id` is an in-memory attribute with no ORM mapping, and there is no raw SQL against `jobs` |

`email` and `celery_task_id` are dead schema ballast: they exist in one app's
table and in no code path. They are irrelevant to the intersection and were
deliberately ignored when it was cut.

### The asymmetry that makes this safe

An **extra** column in the physical table is harmless to a `JobColumns`
subclass — SQLAlchemy simply does not map it. A **missing** column is not: the
first query against it fails at runtime. Cutting the intersection rather than
the union is what makes the mixin safe across several physical schemas.

### The run-owned columns, and the transitions that write them

`status`, `submitted`, `heartbeat_at` and `run_id` are **run-owned**
(`db_manager.RUN_OWNED_COLUMNS`, also importable as `job.RUN_OWNED_COLUMNS`):
only the named transitions of `cosmo_ecosystem.job_run` write them, each one a
single conditional update that says whether it applied
([ADR 0005](../adr/0005-job-status-has-named-owners.md)). No save writes them: a
Job loaded earlier must not put an old state back.

| Transition | From | Writes | Returns |
| --- | --- | --- | --- |
| `mark_queued(job_id)` | PENDING, FAILED | RUNNING, heartbeat and run id NULL, `submitted` true | bool |
| `mark_pending(job_id)` | PENDING, FAILED, COMPLETED | PENDING, heartbeat and run id NULL, `submitted` kept | bool |
| `mark_cancelled(job_id)` | RUNNING | FAILED, plus one job log line | bool |
| claim (in `run`) | RUNNING, no heartbeat | heartbeat `now()`, fresh `run_id` | |
| heartbeat, end (in `run`) | RUNNING, own `run_id` | heartbeat, COMPLETED or FAILED | |
| `mark_start_failed(job_id)` | RUNNING, no heartbeat, no run id | FAILED | bool |
| sweep | RUNNING, stale heartbeat | FAILED | ids |

Every job class keeps these rules (the framework `Job` does):

- **Submit runs the guard first**: `if not job_run.mark_queued(job_id): return False`,
  before the work dir pull, the save and the enqueue. A lost guard has no side
  effect; log it at DEBUG. `submit` returns a bool.
- **A reset goes through `job_run.mark_pending(job_id)`**, first, before anything is
  deleted, and reports a refusal (the job is RUNNING). An app without a reset that
  resubmits a FAILED job directly (COSMOPOLITAN) is covered by `mark_queued` alone.
- **A cancel is `job_run.mark_cancelled(job_id)`**, after the app revoked the task.
  A job that already finished stays as it is.
- **A save filters its row with `RUN_OWNED_COLUMNS`.** `DbManager.add_entry` also
  skips them when it updates an existing row; a new row starts PENDING and not
  submitted. An attribute save (`Job.save_attributes`) names none of them.
- **Input goes onto an existing row only through
  `job_persistence.update_input(job_id, columns)`** (framework `Job.save_input`):
  one update `WHERE status = 'PENDING'` of the input columns, returning whether it
  applied; it never writes `start_date`. Creating a job still inserts.
- **A delete goes through `job_persistence.delete_job`/`delete_jobs`**: the row goes
  first, by `DbManager.delete_job`, one conditional delete returning a bool. A
  RUNNING job is refused (`False`, or the refused ids), nothing of it is deleted
  (no files, no job log), and the page tells the user to cancel or wait. The
  remote prefix, work dir and job log follow; a storage failure after the row delete
  leaves a remote orphan (reported by `job_retention.find_orphaned_prefixes`)
  instead of a row to retry, which is accepted. The retention cleanup skips RUNNING rows and
  purges `job_logs` records without a job row.
- **A failed enqueue writes FAILED through `job_run.mark_start_failed`**, which only
  fails a row that is still a queued run.

`job_run.run` returns `None` for a delivery that lost the claim and for a run that
was overtaken (cancelled, swept as lost, reset, replaced by a newer run): the app's
task returns at once then, before any post-run work (end mail, `notified_end`).
`DbManager.set_submitted` is gone.

### Changing it

Adding a column to `JobColumns` is a framework-wide schema commitment: every
consuming app's `init.sql` has to grow the column *first*, in a release that
ships before the framework tag that maps it. The reverse order breaks whichever
app deploys last.

App-specific columns never go on `JobColumns`. An app maps them on its own
concrete class, same as `input_data` above.

---

## The framework `Job`'s extra-column contract

`JobColumns` fixes the columns every app has. The concrete
`cosmo_ecosystem.job.Job` needs one more and reads and writes it on every load
and save:

| Column | Holds |
| --- | --- |
| `input_data` | the config model as a JSON string (`model_dump_json`) |

An app that uses `Job` declares it on its table, as in the `JobTable` example
above, and in its own `init.sql`. An app with its own job class (COSMONAUT) does
not need it.

`logs` was required too, to carry the text of the job's log file. Since the job
log moved into `job_logs` it is neither required, read nor written: a table that
still has the column keeps working (`job.LEGACY_LOGS_COLUMN` is skipped on load
and save), and the app drops it once no older version runs against the table.
`Job.reload_logs` reads `job_log.read`; `Job.delete_logs` and `Job.reset` clear
the job log.

`Job.__init__` checks `DbManager.job_table` and raises `RuntimeError` naming the
missing column, the same fail-loud pattern as `Job.config_model is None`. Without
the check the first query against the column fails at runtime, in whichever
callback touches the job first. The required names are
`job.REQUIRED_EXTRA_COLUMNS`.

`Job(job_id)` reads the row only and runs no rclone. Code that reads or writes the
job's files calls `job_persistence.work_dir(job_id)` first; see
[ADR 0001](../adr/0001-remote-prefix-is-authoritative.md).

---

## Tables the framework declares, and every app creates

The framework maps two tables of its own on `Base`. Unlike `jobs`, they are not
an intersection — they are the schema, and every app's `init.sql` must create
them exactly so. A missing one fails at runtime, on the first write.

### `LogTable` (`logs`)

`LogTable` is the one table that lifted cleanly: identical in all three code
bases, owned by the framework, written by `logger.PostgreSQLHandler` and read by
the logs page. Rows older than the domain module's `log_retention_days` are
purged by the framework cleanup task, nightly at 03:00.

### `JobLogTable` (`job_logs`)

The job log: one row per record of a job's latest job run, written by
`job_log.JobLogHandler` during `job_run.run`, read by `job_log.read` and cleared
by `job_log.clear` (at the start of every run, on `Job.reset` /
`Job.delete_logs`, and by `job_persistence.delete_job`). It is separate from
`logs` so the 60-day purge does not cut a job log short and worker noise stays
out.

```sql
CREATE TABLE IF NOT EXISTS job_logs (
    id BIGSERIAL PRIMARY KEY,
    job_id VARCHAR NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    level VARCHAR(10) NOT NULL,
    module VARCHAR NOT NULL,
    message TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS job_logs_job_id_idx ON job_logs (job_id);
```

`module` is an unbounded `VARCHAR` on purpose (`logs` has `VARCHAR(50)`): the
handler writes a batch in one insert, and one long module name must not fail
the whole batch. There is no foreign key to `jobs`: COSMONAUT's job table is its
own, and a job log is cleared explicitly with the job.

### Applying DDL to the UFZ databases

The app's `_rw` role has no `CREATE`, so DDL runs as the `_adm` role, with the
password taken from `~/.pgpass` (`psql -w`). Each app's `./schema_diff.sh <host> <db>
<user>` compares a live database with its `docker/init.sql`, read-only. Run it before
and after the DDL.

Check the grants with a catalog query, because psql's `\dp` / `\d` fail here: the
local psql is newer than the UFZ servers, and the meta-command errors out (`operator is
not unique: unknown || "char"`). With `ON_ERROR_STOP`, that also aborts everything
after it in the script.

```sql
SELECT relname, relacl FROM pg_class WHERE relname LIKE 'job_logs%';
```

New tables get the `_rw`/`_ro` grants from the `_adm` role's default privileges;
grant explicitly anyway, so the DDL does not depend on them. Prove the `_rw` role
can write with an insert as `_rw` inside `BEGIN … ROLLBACK`.
