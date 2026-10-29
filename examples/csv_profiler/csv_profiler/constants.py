"""HTML ID constants for the CSV profiler workflow pages.

Domain-specific ids for the example's home / input / job_submission / results
pages, plus the job-reset modal shared by input and job_submission. Shared
framework ids (URL_LOCATION, LOADING_OVERLAY, …) come from
``cosmo_ecosystem.constants``.

Naming convention: <NAME>_<TYPE>_<PAGE>_ID (see docs/conventions/html_ids.md).
"""

# =============================================================================
# SHARED (job reset, see csv_profiler/job_reset.py)
# =============================================================================

# --- Buttons ---
RESET_CANCEL_BUTTON_SHARED_ID = "reset-cancel-button-shared-id"
RESET_CONFIRM_BUTTON_SHARED_ID = "reset-confirm-button-shared-id"

# --- Divs ---
RESET_BODY_DIV_SHARED_ID = "reset-body-div-shared-id"

# --- Modals ---
RESET_CONFIRM_MODAL_SHARED_ID = "reset-confirm-modal-shared-id"

# --- Stores ---
RESET_JOB_STORE_SHARED_ID = "reset-job-store-shared-id"

# =============================================================================
# HOME
# =============================================================================

# --- Buttons ---
START_BUTTON_HOME_ID = "start-button-home-id"

# --- Inputs ---
JOB_INPUT_HOME_ID = "job-input-home-id"

# --- FormTexts ---
JOB_FEEDBACK_FORMTEXT_HOME_ID = "job-feedback-formtext-home-id"

# =============================================================================
# INPUT
# =============================================================================

# --- Buttons ---
CHECK_INPUT_BUTTON_INPUT_ID = (  # nocheck - used via FormFactory
    "check_input_button_input_id"
)
RESET_JOB_BUTTON_INPUT_ID = "reset-job-button-input-id"

# --- Divs ---
HEADER_DIV_INPUT_ID = (
    "header-div-input-id"  # nocheck - used via landing_page_layout_column
)
MAIN_CONTENT_DIV_INPUT_ID = "main-content-div-input-id"

# --- Uploads ---
CSV_UPLOAD_INPUT_ID = "csv-upload-input-id"

# --- Feedback ---
UPLOAD_FEEDBACK_DIV_INPUT_ID = "upload-feedback-input-id"

# --- Stores ---
JOB_STORE_INPUT_ID = "job-store-input-id"
FORM_VALID_STORE_INPUT_ID = "form-valid-store-input-id"
UPLOADED_FILE_NAME_STORE_INPUT_ID = "uploaded-file-name-store-input-id"

# =============================================================================
# JOB_SUBMISSION
# =============================================================================

# --- Buttons ---
SUBMIT_BUTTON_JOB_SUBMISSION_ID = "submit-button-job-submission-id"
CHANGE_INPUT_BUTTON_JOB_SUBMISSION_ID = "change-input-button-job-submission-id"
VIEW_RESULTS_BUTTON_JOB_SUBMISSION_ID = "view-results-button-job-submission-id"
RESUBMIT_BUTTON_JOB_SUBMISSION_ID = "resubmit-button-job-submission-id"

# --- Divs ---
HEADER_DIV_JOB_SUBMISSION_ID = (
    "header-div-job-submission-id"  # nocheck - used via landing_page_layout_column
)
MAIN_CONTENT_DIV_JOB_SUBMISSION_ID = "main-content-div-job-submission-id"
STATUS_DIV_JOB_SUBMISSION_ID = "status-div-job-submission-id"
JOB_LOGS_DIV_JOB_SUBMISSION_ID = "job-logs-div-job-submission-id"

# --- Intervals ---
INTERVAL_JOB_SUBMISSION_ID = "interval-job-submission-id"

# --- Stores ---
JOB_STORE_JOB_SUBMISSION_ID = "job-store-job-submission-id"

# --- Accordions ---
ACCORDION_JOB_SUBMISSION_ID = "accordion-job-submission-id"

# --- Icons ---
ICON_JOB_SUBMISSION_ID = "icon-job-submission-id"

# =============================================================================
# RESULTS
# =============================================================================

# --- Buttons ---
BACK_BUTTON_RESULTS_ID = (
    "back-button-results-id"  # nocheck - used as href button, testing only
)

# --- Divs ---
HEADER_DIV_RESULTS_ID = "header-div-results-id"
MAIN_CONTENT_DIV_RESULTS_ID = "main-content-div-results-id"

# --- Stores ---
JOB_STORE_RESULTS_ID = "job-store-results-id"

# --- Tables ---
SUMMARY_TABLE_RESULTS_ID = "summary-table-results-id"  # nocheck - testing only
