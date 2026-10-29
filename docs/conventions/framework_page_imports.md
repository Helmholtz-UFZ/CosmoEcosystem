# What a Consumer Inherits When It Imports a Framework Page

An app registers a framework page by importing it:

```python
import cosmo_ecosystem.pages.logs           # noqa: F401
import cosmo_ecosystem.pages.job_management  # noqa: F401
import cosmo_ecosystem.pages.worker_management  # noqa: F401
```

That import does far more than add a route. Dash pages register themselves, and
callbacks wire themselves, **at import time** — so the import runs code, pulls in
a transitive module graph, and claims a set of HTML ids in the app's global
callback registry.

Everything on this page has been measured in a running app. The reason it has
its own convention file is that all of it fails the same way: **no import error,
no failing test, and a symptom that surfaces somewhere else entirely.**

---

## What comes along

| Importing … | also imports | which registers |
| --- | --- | --- |
| any framework page | `cosmo_ecosystem.layouts` | nothing since v0.7.0 — the navbar-collapse callback used to be here, see [silent failure 4](#4-an-import-registers-a-callback-and-a-consumer-never-asked) |
| `pages.job_management` | `cosmo_ecosystem.job_retention`, `cosmo_ecosystem.job_persistence`, `cosmo_ecosystem.db_manager` (not `cosmo_ecosystem.job`: it cleans through `job_retention` and deletes through `job_persistence`) | its own page + two callbacks, one of them clientside (the overlay opener). Raises `JobLinkNotConfigured` instead when `cosmo_ecosystem.pages.job_link` is unset |
| `pages.worker_management` | `cosmo_ecosystem.background_job_manager` | its own page + eleven callbacks, one of them clientside |
| `layouts.app_layout()` | — | the navbar-collapse callback on `NAVBAR_TOGGLER_BUTTON_SHARED_ID` / `NAVBAR_COLLAPSE_DIV_SHARED_ID` — it mounts that navbar |
| `layouts.register_navbar_callbacks()` | — | the navbar-collapse callback, for an app that mounts the shared id in a navbar of its own |

Two consequences follow from "at import time":

1. **Every seam must be set before the import.** `Job.config_model`,
   `Job.submit_handler`, `Job.app_version`, `layouts.default_wrapper_class`,
   `pages.job_link` — configure them, *then* import the pages.
   `pages/job_management.py` builds its `layout` as a module-level statement, so a
   value set afterwards reaches the other two pages and silently misses that one.
   Assign the module attribute; a `from … import` binds a copy and configures
   nothing.

   `cosmo_ecosystem.pages.job_link` is the one that is **required**: a callable
   `(job_id: str, row: dict) -> str` giving the href of a row in the job
   management table, where `row` is the job's full `DbManager.list_jobs()` entry
   (so a link may depend on `status` or an app-only column such as COSMONAUT's
   `stage`). It has no default, and the page raises `JobLinkNotConfigured` at
   import while it is unset — a forgotten link would otherwise only show as a
   table of dead links. It sits on the `pages` package, not on the page module,
   because a module's own attribute cannot be assigned before that module is
   imported; importing the package imports no page.

   ```python
   import cosmo_ecosystem.pages
   cosmo_ecosystem.pages.job_link = lambda job_id, row: f"/job-submission/{job_id}"
   import cosmo_ecosystem.pages.job_management  # noqa: E402, F401
   ```
2. **Order matters relative to `Dash()`.** `register_page` needs the app to
   exist, which is why the example imports the framework pages *after* the
   `Dash(...)` call rather than at the top of `app.py`.

---

## The four silent failures

### 1. A duplicate callback aborts the whole registry

If the app already registers a callback on an id that `cosmo_ecosystem.layouts`
claims, Dash does not fail that one callback. It aborts the **entire** callback
registry, so the visible symptom is an unrelated page that has simply stopped
reacting to clicks. COSMOPOLITAN hit this in Slice 1b and resolved it by dropping
its local duplicate; COSMONAUT will meet it in Slice 2, the first time it calls
`layouts.app_layout()`.

**Rule:** before importing a framework page, check the ids in
`cosmo_ecosystem/constants/html_ids.py` marked `SHARED` against the app's own
callbacks. A collision is resolved by removing the app's copy, not by aliasing
the id — two callbacks writing the same component is the bug, whatever it is
called.

### 2. A same-named exception makes `except` stop matching

`ObjectStorageError` exists in the framework and existed under the same name in
the app. After the switch, `except ObjectStorageError` in app code caught a class
that framework code never raises. The `except` clause is still there, still reads
correctly, and never fires again; the error escapes to the global handler and the
user gets "Internal Error" instead of the intended message.

The same trap is open today for `FileValidationError`, which the framework
defines and COSMOPOLITAN also gets from
`soil_moisture_prediction.input_file_parser` — see
[error handling](error_handling.md#exception-name-collisions-with-domain-packages).

**Rule:** when adopting a framework exception, grep for every `except <Name>` in
the app and confirm each one now refers to the framework class. Never let two
classes with one name coexist in a process; either import the framework's, or
wrap the foreign one at the boundary where it is raised.

### 3. A relative path resolves against the wrong root

`WEB_WORK_DIR` shipped as `./work_dir` in the `.env` files. Flask's
`send_from_directory` resolves a relative directory against `app.root_path` — the
*installed app package* — not against the process's working directory. Every job
file 404s, and nothing else breaks. `cosmo_ecosystem/config.py` now absolutises the
value at import time, and the comment there records why.

**Rule:** any path a consumer configures is absolutised where the framework reads
it, not where it is used. A relative path that happens to work is a coincidence
of the container's working directory.

### 4. An import registers a callback, and a consumer never asked

Until v0.7.0, `cosmo_ecosystem/layouts.py` carried `toggle_navbar_collapse` as a
module-level `@callback`. Every framework page imports `layouts`, so importing
any page registered it. Measured on `origin/main` of both apps, that one line did
two different silent things:

| App | Its collapse id | What the module-level callback actually did |
| --- | --- | --- |
| COSMOPOLITAN | `navbar-collapse-div-shared-id` — the framework id, mounted in the app's *own* navbar | the navbar toggle worked, and worked **only** as a side effect of the import. The app has no callback of its own. |
| COSMONAUT | `navbar-collapse-nav-shared-id`, with its own callback | the framework callback was registered against an id that is never mounted: dead weight in the registry. |

Note what this is *not*. It is not the duplicate-callback abort of failure 1 —
the ids differ, so Dash sees nothing wrong, and nothing crashes on either side.
It is an invisible dependency in one app and an invisible no-op in the other. The
day COSMOPOLITAN stops importing a framework page, its hamburger menu stops
opening on small screens, with no error, no log line and no failing test.

**Rule:** an *import* registers no callbacks. Not "a library module registers
none" — the defect is the import, not the framework. A function that mounts a
component and wires that same component in the same call is co-location, and
`app_layout()` does exactly that with the navbar. What must never happen is
`import cosmo_ecosystem.layouts` doing it behind an app's back.

A page module is the deliberate exception in the other direction: registering
itself at import is what a page is *for*.

Which registration goes where follows from whether the component is optional:

| | mounted by | registration |
| --- | --- | --- |
| navbar | `app_layout()`, always | called by `app_layout()`. There is no call in which the callback is unwanted. |
| reset modal (example only, since v0.13.0) | the app, appending `job_reset_components()` to its shell | called by that same function. The framework ships no reset: it was bound to the concrete `Job`, and an app that has none would carry callbacks that can never fire. |

`register_navbar_callbacks()` stays public and idempotent for the app that
mounts `NAVBAR_COLLAPSE_DIV_SHARED_ID` in a navbar of its own and never calls
`app_layout()` — COSMOPOLITAN's case, and the one line of rework this change
costs it.

`test_layouts.py` parses `layouts.py` and fails on any module-level `@callback`,
so the import-time form cannot quietly come back; two more tests pin that
`app_layout()` does the registration and does not duplicate it when Dash calls
the layout per request.

---

## The pattern behind all four

A name, an id, a path or a registration takes effect **somewhere other than
where it was written**, and the wrong outcome is a legal program. Python raises
nothing, the test suite exercises neither path, and the symptom appears in a
different page, a different callback, or a different service.

When adding anything to the framework that a consumer inherits by importing —
a shared callback, an exception class, a configured path, an HTML id, a
registration — ask
whether a consumer could already own that name, and whether they would find out.
If the answer is "not until a user complains", the seam belongs in this file
before it belongs in the code.
