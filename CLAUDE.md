## Project Overview

Cosmo Ecosystem is the shared Dash + Celery + PostgreSQL + S3 application framework used
by COSMOPOLITAN and COSMONAUT. This repo is the framework's home; it also ships a
reference domain, `examples/csv_profiler/` — a CSV statistical profiler — that
demonstrates how to integrate a Python computation module into the framework.

## Architecture

The application is built as a Dash web application with the following key components:

- **Web Framework**: Dash (plotly) with Flask server backend
- **Database**: PostgreSQL (plain, no PostGIS)
- **Object Storage**: S3 (UFZ S3 in prod, RustFS locally and in CI) via rclone
- **Background Tasks**: Celery with Redis broker for distributed task processing

### Core Modules

- `app.py` - Main application entry point with Dash app initialization
- `db_manager.py` - Database ORM models and operations using SQLAlchemy
- `object_storage_manager.py` - Object storage management via rclone
- `computation_module.py` - CSV statistical profiler (the example computation)
- `pydantic_models.py` - ProfileConfig Pydantic model for job configuration
- `job.py` - Job processing and workflow management
- `background_job_manager.py` - Celery task management and job orchestration
- `pages/` - Individual page components for the multi-page application
- `tasks/` - Celery task definitions
  - `computation_tasks.py` - CSV profiling job processing
  - `maintenance_tasks.py` - Periodic cleanup tasks

### Pages

- `home.py` - Welcome page explaining what the template is
- `job_submission.py` - Upload CSV, configure profiling, submit job
- `results.py` - View profiling results (stats table, charts, correlation heatmap)
- `job_management.py` - AG Grid table of all jobs with status and actions
- `logs.py` - Log viewer
- `worker_management.py` - Celery worker status

## Sister Projects

This framework is derived from two sister projects that share the same architecture:

- **COSMOPOLITAN** (`../cosmopolitan`) — CRNS soil moisture prediction, uses PostGIS
- **COSMONAUT** (`../ufz-cosmonaut`) — Navigation route optimization, uses Dash Leaflet

Patterns and conventions in this framework apply symmetrically to both.

## Convention Philosophy

All conventions are norms, not hard rules. A convention may be violated when there is a
good reason — but the violation must be accompanied by a comment explaining why.

## Critical Anti-Patterns

**DO NOT:**

1. **No defensive programming**

   - NO `dict.get()` - use direct access `dict["key"]`
   - NO bare `except Exception` - always catch specific exceptions

2. **No inline imports**

   - All imports at TOP LEVEL ONLY
   - Never import inside functions

3. **HTML IDs - Restricted Usage**

   - MUST use constants from `src/constants/html_ids.py`
   - NEVER use literal ID strings
   - ONLY create IDs for:
     1. Components used in callbacks (Input/Output/State)
     2. Components used in tests (Playwright locators)
     3. Components used with `set_props()` (requires `# nocheck`)
     4. Dynamically constructed IDs (requires `# nocheck`)
   - **LLMs tend to over-create IDs - resist this tendency**

4. **No inline CSS**

   - Use Bootstrap classes only
   - Existing `style={}` usages are violations to clean up later

## Proactive Issue Reporting

When you spot bad practices, convention violations, symmetric bugs, or fragile patterns
— even if unrelated to the current task — flag them briefly and ask: "Want me to fix it?"

## Memory Policy

**DO NOT** use the auto memory system (`MEMORY.md`).

When you discover something worth preserving — a non-obvious gotcha, a hard-won
debugging insight, a pattern that should be followed — ask the user where to record it.
The options are:

- **`CLAUDE.md`** — High-level rules and project-wide constraints
- **An existing `docs/conventions/*.md`** — Extend the relevant convention file
- **A new `docs/conventions/*.md`** — If no existing file fits, propose creating one.
  Do not hesitate to do this; a focused new file is better than cramming unrelated
  knowledge into an existing one.

Always prefer the most specific home for the knowledge.

## Detailed Conventions

For specific implementation details, see:

- [Testing](docs/conventions/testing.md) - Test execution and pipeline
- [Error Handling](docs/conventions/error_handling.md) - Custom exceptions, error modal
- [Layout](docs/conventions/layout.md) - Reusable components, flex patterns
- [Bootstrap Styling](docs/conventions/bootstrap_styling.md) - Bootstrap classes only
- [Logging](docs/conventions/logging.md) - Log levels, proper logger usage
- [Callbacks](docs/conventions/callbacks.md) - Callback organization patterns
- [HTML IDs](docs/conventions/html_ids.md) - ID naming and restricted usage
- [Environment Variables](docs/conventions/environment_variables.md) - Env files, config loading
- [Config Model Contract](docs/conventions/config_model_contract.md) - The Job config-model seam
- [Framework Page Imports](docs/conventions/framework_page_imports.md) - What a consumer inherits by importing a page, and how it fails silently
- [Database Schema](docs/conventions/database_schema.md) - Shared `Base`, the `JobColumns` intersection mixin, DDL ownership
- [Object Storage](docs/conventions/object_storage.md) - The S3 server for dev/CI, the shared CI template, wiring up an app, swapping the server
- [Celery Beat](docs/conventions/celery_beat.md) - Beat runs in the worker (`--beat`), never as a thread in `app.py` — fork deadlock / duplicate schedules
- [Worker Image](docs/conventions/worker_image.md) - The Dockerfile `CMD` seam, why `&&` not `;`, and the smoke test that belongs in the apps
- [Cross-Repo Development](docs/conventions/cross_repo_development.md) - Framework and both apps move together; `COSMO_ECOSYSTEM_PATH` overlay, never a committed local path

**Important** read the convention before you make any codebase exploration or answering.
Never sacrfice speed for accuracy.

Which conventions you should read depends on the first user prompt. Determine the
conventions which are important for the current task and read them imediatly. Keep the
conventions in mind and if you have not read them and they become important read them
then.

## Skills

Use the semantic-anchor-translator skill from:
https://github.com/LLM-Coding/Semantic-Anchors/tree/main/skill/semantic-anchor-translator

When the user asks to perform one of these tasks, read the corresponding skill
document first for the step-by-step guide. This is espacially important for tasks the
user asks later. Keep this skill list in Mind:

- [New Page](docs/skills/new_page.md) - Checklist for creating a new page
- [New Module Test](docs/skills/create_module_test.md) - Checklist for creating a new core module test
- [Run and Fix Testing](docs/skills/run_and_fix_testing.md) - Systematic guide for running tests and diagnosing failures
- [Convention Keeper](docs/skills/convention_keeper.md) - Audit and fix convention violations across the codebase

## Identity Files — Read First, No Exceptions

You CANNOT respond to the user until you have attempted to read these files from the
project root. Use the Read tool (not Glob — they are symlinks). If Read fails, try
resolving the symlink target via `ls -la` and read that path. If they don't exist, move
on — but you must try.

1. `SOUL.md` — Who you are
2. `USER.md` — Who you're working with

This applies regardless of what the user asked. A meta-question, a greeting, a one-liner
— doesn't matter. Attempt to read both files before your first response. Every session.
No exceptions.
