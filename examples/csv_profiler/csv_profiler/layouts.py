"""Layout pieces for the CSV profiler's job pages."""

from cosmo_ecosystem.layouts import JOB_STATUS_COLORS, create_header


def create_job_header(title, job):
    """Create a header for job pages, colored by job status.

    Moved here from ``cosmo_ecosystem.layouts`` in v0.13.0: it reads the concrete
    ``Job``, and only this example used it.
    """
    bg_color = JOB_STATUS_COLORS[job.status]
    return create_header(title, job.job_id, bg_color=bg_color)
