"""HTML ID constants for Dash components.

Naming convention: <NAME>_<TYPE>_<PAGE>_ID
- NAME: Semantic purpose (e.g., START_JOB, EMAIL)
- TYPE: Component type (BUTTON, INPUT, DIV, DROPDOWN, STORE, MODAL, ALERT, LINK, etc.)
- PAGE: Page scope (SHARED, HOME, INPUT, JOB_SUBMISSION, RESULTS, etc.)
- ID: Required suffix

See docs/conventions/html_ids.md for full details.
"""

# =============================================================================
# SHARED / GLOBAL
# =============================================================================

# --- Locations ---
URL_LOCATION_SHARED_ID = (
    "url-location-shared-id"  # nocheck - dcc.Location used by Dash routing
)

# --- Modals ---
ERROR_MODAL_SHARED_ID = "error-modal-shared-id"  # nocheck - used via set_props()
LOADING_OVERLAY_MODAL_SHARED_ID = "loading-overlay-modal-shared-id"

# --- Divs ---
ERROR_TITLE_DIV_SHARED_ID = (
    "error-title-div-shared-id"  # nocheck - used via set_props()
)
ERROR_MESSAGE_DIV_SHARED_ID = (
    "error-message-div-shared-id"  # nocheck - used via set_props()
)

# --- Buttons ---
DOWNLOAD_BUTTON_SHARED_ID = (
    "download-button-shared-id"  # nocheck - used in files_route, testing only
)
NAVBAR_TOGGLER_BUTTON_SHARED_ID = "navbar-toggler-button-shared-id"

# --- Collapses ---
NAVBAR_COLLAPSE_DIV_SHARED_ID = "navbar-collapse-div-shared-id"

# --- Reset Confirm Modal ---
RESET_BODY_DIV_SHARED_ID = "reset-body-div-shared-id"
RESET_CANCEL_BUTTON_SHARED_ID = "reset-cancel-button-shared-id"
RESET_CONFIRM_BUTTON_SHARED_ID = "reset-confirm-button-shared-id"
RESET_CONFIRM_MODAL_SHARED_ID = "reset-confirm-modal-shared-id"

# --- Stores ---
RESET_JOB_STORE_SHARED_ID = "reset-job-store-shared-id"


# =============================================================================
# WORKER_MANAGEMENT
# =============================================================================

# --- Buttons ---
CANCEL_MODAL_CANCEL_BUTTON_WORKER_MANAGEMENT_ID = (
    "cancel-modal-cancel-button-worker-management-id"
)
CANCEL_MODAL_CONFIRM_BUTTON_WORKER_MANAGEMENT_ID = (
    "cancel-modal-confirm-button-worker-management-id"
)
KILL_MODAL_CANCEL_BUTTON_WORKER_MANAGEMENT_ID = (
    "kill-modal-cancel-button-worker-management-id"
)
KILL_MODAL_CONFIRM_BUTTON_WORKER_MANAGEMENT_ID = (
    "kill-modal-confirm-button-worker-management-id"
)
TEST_TASK_BUTTON_WORKER_MANAGEMENT_ID = "test-task-button-worker-management-id"
WORKER_CANCEL_BTN_WORKER_MANAGEMENT_ID = "worker-cancel-btn-worker-management-id"
WORKER_KILL_BTN_WORKER_MANAGEMENT_ID = "worker-kill-btn-worker-management-id"
WORKER_REFRESH_BTN_WORKER_MANAGEMENT_ID = "worker-refresh-btn-worker-management-id"

# --- Divs ---
CANCEL_MODAL_TASK_INFO_DIV_WORKER_MANAGEMENT_ID = (
    "cancel-modal-task-info-div-worker-management-id"
)
KILL_MODAL_TASK_INFO_DIV_WORKER_MANAGEMENT_ID = (
    "kill-modal-task-info-div-worker-management-id"
)
WORKER_LAST_REFRESH_DIV_WORKER_MANAGEMENT_ID = (
    "worker-last-refresh-div-worker-management-id"
)
WORKER_MANAGEMENT_DUMMY_COMPONENT_WORKER_MANAGEMENT_ID = (
    "worker-management-dummy-component-worker-management-id"
)
WORKER_STATS_CARD_DIV_WORKER_MANAGEMENT_ID = (
    "worker-stats-card-div-worker-management-id"
)

# --- Modals ---
CANCEL_MODAL_WORKER_MANAGEMENT_ID = "cancel-modal-worker-management-id"
KILL_MODAL_WORKER_MANAGEMENT_ID = "kill-modal-worker-management-id"

# --- Tables ---
ACTIVE_TASKS_TABLE_WORKER_MANAGEMENT_ID = "active-tasks-table-worker-management-id"
RESERVED_TASKS_TABLE_WORKER_MANAGEMENT_ID = "reserved-tasks-table-worker-management-id"
REVOKED_TASKS_TABLE_WORKER_MANAGEMENT_ID = "revoked-tasks-table-worker-management-id"
SCHEDULED_TASKS_TABLE_WORKER_MANAGEMENT_ID = (
    "scheduled-tasks-table-worker-management-id"
)

# =============================================================================
# JOB_MANAGEMENT
# =============================================================================

# --- Buttons ---
DELETE_BUTTON_JOB_MANAGEMENT_ID = "delete-button-job-management-id"
CLEAN_BUTTON_JOB_MANAGEMENT_ID = "clean-button-job-management-id"
REFRESH_BUTTON_JOB_MANAGEMENT_ID = "refresh-button-job-management-id"

# --- Stores ---
DUMMY_STORE_JOB_MANAGEMENT_ID = "dummy-store-job-management-id"

# --- Tables ---
JOBS_TABLE_JOB_MANAGEMENT_ID = "jobs-table-job-management-id"

# =============================================================================
# LOGS
# =============================================================================

# --- DatePickers ---
DATE_RANGE_DATEPICKER_LOGS_ID = "date-range-datepicker-logs-id"

# --- Divs ---
LOG_OUTPUT_DIV_LOGS_ID = "log-output-div-logs-id"
TIME_ERROR_DIV_LOGS_ID = "time-error-div-logs-id"

# --- Dropdowns ---
LOG_LEVELS_DROPDOWN_LOGS_ID = "log-levels-dropdown-logs-id"

# --- Input Groups ---
TIME_INPUT_GROUP_LOGS_ID = "time-input-group-logs-id"

# --- Inputs ---
START_HOUR_INPUT_LOGS_ID = "start-hour-input-logs-id"
START_MINUTE_INPUT_LOGS_ID = "start-minute-input-logs-id"
END_HOUR_INPUT_LOGS_ID = "end-hour-input-logs-id"
END_MINUTE_INPUT_LOGS_ID = "end-minute-input-logs-id"
PID_INPUT_LOGS_ID = "pid-input-logs-id"

# --- Buttons ---
REFRESH_BUTTON_LOGS_ID = "refresh-button-logs-id"

# --- Checklists ---
PID_RADIO_CHECKLIST_LOGS_ID = "pid-radio-checklist-logs-id"
LIVE_MODE_CHECKLIST_LOGS_ID = "live-mode-checklist-logs-id"

# --- Dropdowns (continued) ---
MODULE_EXCLUDE_DROPDOWN_LOGS_ID = "module-exclude-dropdown-logs-id"

# --- Intervals ---
AUTO_POLL_INTERVAL_LOGS_ID = "auto-poll-interval-logs-id"
