"""CSV profiler configuration model (the domain config for the framework Job).

`ProfileConfig` subclasses `cosmo_ecosystem.pydantic_models.UploadJobConfig`, which
provides the framework-required `job_id` and `upload_file_name` fields. The app
injects this class via `Job.config_model` at startup. Apps that do not use the
framework `Job` subclass the smaller `BaseJobConfig` instead (job_id only).
"""

from typing import Annotated, Literal, Optional

from pydantic import Field

from cosmo_ecosystem.pydantic_models import UploadJobConfig


class ProfileConfig(UploadJobConfig):
    """Configuration for CSV statistical profiling."""

    columns: Optional[list[str]] = Field(
        None,
        description="Which columns to analyze (default: all)",
        title="Columns",
        json_schema_extra={"type": "dropdown-checklist"},
    )

    handle_missing: Annotated[
        Literal["drop", "fill_mean", "fill_zero", "keep"],
        Field(
            "drop",
            description="How to handle missing values",
            title="Handle missing values",
            json_schema_extra={"type": "select"},
        ),
    ]

    histogram_bins: Annotated[
        int,
        Field(
            30,
            description="Number of bins for histograms (5–200)",
            title="Histogram bins",
            ge=5,
            le=200,
            json_schema_extra={"type": "integer"},
        ),
    ]

    compute_correlation: Annotated[
        bool,
        Field(
            True,
            description="Compute correlation matrix for numeric columns",
            title="Compute correlation",
            json_schema_extra={"type": "checkbox"},
        ),
    ]

    top_n_categories: Annotated[
        int,
        Field(
            10,
            description="Number of top values for categorical columns (1–100)",
            title="Top N categories",
            ge=1,
            le=100,
            json_schema_extra={"type": "integer"},
        ),
    ]

    trigger_error: Annotated[
        bool,
        Field(
            False,
            description="Deliberately trigger a division by zero error (for testing)",
            title="Trigger error",
            json_schema_extra={"type": "checkbox"},
        ),
    ]
