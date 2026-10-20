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
```

Each app declares its own concrete class from it, on the framework `Base`,
alongside whatever extra columns its own `jobs` table carries:

```python
from cosmo_ecosystem.db_manager import Base, JobColumns

class JobTable(JobColumns, Base):
    __tablename__ = "jobs"

    input_data = Column(JSON)
    logs = Column(String)
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
has neither. The `v0.5.0` cut had included them, measured only against
COSMOPOLITAN and csv_profiler, and broke the first time COSMONAUT tried to
declare a job table against it.

What stays app-side, and why:

| Column | Where | Why it is not in the intersection |
| --- | --- | --- |
| `input_data`, `logs` | COSMOPOLITAN, csv_profiler `init.sql` | COSMONAUT's `jobs` table has neither |
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

### Changing it

Adding a column to `JobColumns` is a framework-wide schema commitment: every
consuming app's `init.sql` has to grow the column *first*, in a release that
ships before the framework tag that maps it. The reverse order breaks whichever
app deploys last.

App-specific columns never go on `JobColumns`. An app maps them on its own
concrete class, same as `input_data` and `logs` above.

---

## `LogTable`

`LogTable` is the one table that lifted cleanly: identical in all three code
bases, owned by the framework, written by `logger.PostgreSQLHandler` and read by
the logs page. It is not an intersection — it is the schema.
