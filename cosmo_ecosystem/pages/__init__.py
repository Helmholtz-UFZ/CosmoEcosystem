"""Dash pages package for Cosmo Ecosystem multi-page application."""

# Seam: where a row of the job management page links to, a callable
# `(job_id: str, row: dict) -> str`; `row` is the job's full `DbManager.list_jobs()`
# entry, so a link may depend on any column (COSMONAUT's depends on status and
# stage). Required: `pages/job_management.py` raises `JobLinkNotConfigured` at
# import time while it is unset, rather than render a table of dead links.
#
# It lives on the package, not on the page module, because it must be set BEFORE
# the page is imported, and a module's own attribute cannot be assigned before
# the module exists. Importing this package imports no page. Same rule as
# `layouts.default_wrapper_class`, see docs/conventions/framework_page_imports.md:
#
#     import cosmo_ecosystem.pages
#     cosmo_ecosystem.pages.job_link = lambda job_id, row: f"/job-submission/{job_id}"
#     import cosmo_ecosystem.pages.job_management  # noqa: E402, F401
#
# Assign the package attribute; a `from … import job_link` binds a copy of the
# value and configures nothing.
job_link = None
