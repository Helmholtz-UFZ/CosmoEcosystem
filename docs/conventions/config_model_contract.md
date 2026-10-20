# Convention: the config-model contract (`UploadJobConfig`)

A `cosmo_ecosystem` `Job` is generic over its configuration `model`. A domain
plugs its configuration into the framework by injecting four class attributes on
`Job` at application startup — in **both** the web app (`app.py`) and the Celery
worker entrypoint (`celery_app.py`), **before any `Job` is constructed**:

```python
Job.config_model   = ProfileConfig                        # an UploadJobConfig subclass
Job.file_validator = staticmethod(validate_csv)           # optional; None = no-op
Job.submit_handler = staticmethod(submit_computation_job)
Job.app_version    = version("csv-profiler")              # optional; provenance stamp
```

## The `config_model` contract

`Job.config_model` MUST be a subclass of
`cosmo_ecosystem.pydantic_models.UploadJobConfig`, which provides the two fields the
framework `Job` relies on generically:

- **`job_id: str`** — validated by `validate_job_id`; the job's identity.
  Contributed by `BaseJobConfig`, together with `validate_assignment=True`, so
  an invalid id cannot be assigned after construction either.
- **`upload_file_name: str | None`** — the single uploaded input file the `Job`
  tracks (used by `Job.upload_file` and `Job.reset`). Contributed by
  `UploadJobConfig`.

A domain config model adds its own fields on top (the CSV profiler example adds
`handle_missing`, `histogram_bins`, `compute_correlation`, …).

### Which base to subclass

The two layers exist because `upload_file_name` is not part of a job
configuration's minimal contract — it belongs to the framework `Job`'s usage
pattern, and an app whose job table has no such column would have to invent one
just to satisfy the base class (measured in COSMONAUT: `save()` broke on the
missing column).

| Your app… | Subclass |
|---|---|
| uses `cosmo_ecosystem.job.Job` | **`UploadJobConfig`** |
| keeps its own `Job` class | **`BaseJobConfig`** (job_id contract only) |

`Job.config_model` is **fail-loud**: it defaults to `None`, and constructing a
`Job` without setting it raises `RuntimeError`. `file_validator` may stay `None`
(no-op); `submit_handler` fails loud only when `Job.submit()` is actually called.

## The `app_version` seam

Every job records the version of the code that produced it in its `version`
column. `Job.app_version` defaults to the **framework's** own version (read from
the installed distribution metadata, so it cannot drift from `pyproject.toml`).

An app with its own release cycle should inject its own version — otherwise its
jobs are stamped with the framework's version, which says nothing about the
domain code that computed the result. Injecting it in `app.py` alone is not
enough: `celery_app.py` constructs `Job`s in the worker process too, and an
unset seam there silently stamps the framework version on worker-created jobs.

## Why injection, not import

Injecting the config model (rather than importing it) is what keeps
`cosmo_ecosystem` domain-free: the package never imports the domain, and CI
enforces this with a grep gate. This is the Phase-1 minimal seam; the full
`DomainPlugin` protocol/registry is Layer B (see
`docs/plan/cosmo-core-package-boundary.md`).
