"""Framework pydantic models: job-id validation + the base job-config contract.

The contract comes in two layers:

`BaseJobConfig` is the minimal one — a validated `job_id` and
`validate_assignment=True`. An app whose job table has no upload column
subclasses this and owes the framework nothing else.

`UploadJobConfig` adds `upload_file_name`. That field is not part of the
minimal contract, it belongs to the usage pattern of the framework `Job`, which
persists, reloads, and tracks a single uploaded input file without knowing the
domain. An app adopting `cosmo_ecosystem.job.Job` must therefore subclass
`UploadJobConfig` and inject it via `Job.config_model` at startup.

See docs/plan/cosmo-core-package-boundary.md (config-model contract).
"""

import logging
import re
from typing import Annotated, Optional

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)


def validate_job_id(job_id: str) -> str:
    """Validate job id.

    Job IDs must contain only letters, numbers, or underscores,
    and be between 8 and 50 characters long.
    """
    log.debug(f"Check job id {job_id}")

    job_id_regex = r"^\w+$"
    if not re.match(job_id_regex, job_id):
        raise ValueError("Job id must contain only letters numbers or underscore")

    min_job_id_length = 8
    max_job_id_length = 50

    if len(job_id) < min_job_id_length or len(job_id) > max_job_id_length:
        raise ValueError(
            f"Job id must be between {min_job_id_length} and {max_job_id_length} characters"  # noqa
        )
    return job_id


class BaseJobConfig(BaseModel):
    """Minimal contract for a job's configuration model.

    A validated ``job_id`` plus assignment validation — nothing else. Apps that
    do not use the framework ``Job`` subclass this and add their own fields.
    """

    job_id: Annotated[
        str,
        Field(
            "poised_python_of_wonder",
            description='Identifier for your submission. Only letters, numbers and "_".',
            title="Job ID",
            json_schema_extra={"type": "text"},
        ),
        AfterValidator(validate_job_id),
    ]

    # Security feature: No model can have an invalid job_id
    model_config = ConfigDict(validate_assignment=True)


class UploadJobConfig(BaseJobConfig):
    """Contract for a config model used with the framework ``Job``.

    Adds the single-upload-file tracking that ``Job`` relies on
    (``upload_file``, ``reset``, and the parameters dump all read this field).
    A domain config model for the framework ``Job`` MUST subclass this;
    ``BaseJobConfig`` alone is not enough.
    """

    upload_file_name: Optional[str] = Field(
        None,
        description="Name of the uploaded input file",
        title="Upload file name",
        json_schema_extra={"type": "hidden"},
    )
