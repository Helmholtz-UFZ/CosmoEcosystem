"""End-to-end Playwright tests for the CSV profiler flow.

Tests the full multi-step pipeline: home → input → job submission →
wait for completion → view results.
"""

import logging
import os
import time

import pytest

from playwright.sync_api import expect

from cosmo_ecosystem.config import PORT
from cosmo_ecosystem.constants import (
    DOWNLOAD_BUTTON_SHARED_ID,
    NAVBAR_COLLAPSE_DIV_SHARED_ID,
    NAVBAR_TOGGLER_BUTTON_SHARED_ID,
    RESET_CONFIRM_BUTTON_SHARED_ID,
    RESET_CONFIRM_MODAL_SHARED_ID,
)

from csv_profiler.constants import (
    ACCORDION_JOB_SUBMISSION_ID,
    BACK_BUTTON_RESULTS_ID,
    CHANGE_INPUT_BUTTON_JOB_SUBMISSION_ID,
    CHECK_INPUT_BUTTON_INPUT_ID,
    CSV_UPLOAD_INPUT_ID,
    JOB_INPUT_HOME_ID,
    JOB_LOGS_DIV_JOB_SUBMISSION_ID,
    START_BUTTON_HOME_ID,
    STATUS_DIV_JOB_SUBMISSION_ID,
    SUBMIT_BUTTON_JOB_SUBMISSION_ID,
    SUMMARY_TABLE_RESULTS_ID,
    UPLOAD_FEEDBACK_DIV_INPUT_ID,
    VIEW_RESULTS_BUTTON_JOB_SUBMISSION_ID,
)
from csv_profiler.forms import form_factory
from help_functions_tests import check_all_errors, wait_for_dash_callback

BASE_URL = f"http://localhost:{PORT}"
SAMPLE_CSV = os.path.join(os.path.dirname(__file__), "sample_mixed.csv")
TRIGGER_ERROR_CHECKBOX_ID = form_factory.id_format.format(field_name="trigger_error")


def test_home_page_loads(page, dash_app):
    """Test that the home page loads successfully."""
    page.goto(f"{BASE_URL}/")
    page.set_viewport_size({"width": 1920, "height": 1080})
    expect(page.locator(f"#{START_BUTTON_HOME_ID}")).to_be_visible(timeout=10000)
    wait_for_dash_callback(page)
    check_all_errors(page)
    logging.info("Home page loaded successfully")


def test_navigation_links(page, dash_app):
    """Test that navigation links work."""
    page.goto(f"{BASE_URL}/")
    page.set_viewport_size({"width": 1920, "height": 1080})

    toggler = page.locator(f"#{NAVBAR_TOGGLER_BUTTON_SHARED_ID}")
    if toggler.is_visible():
        toggler.click()

    expect(page.locator(f"#{NAVBAR_COLLAPSE_DIV_SHARED_ID}")).to_be_visible()
    check_all_errors(page)


def test_full_csv_profiling_flow(page, dash_app, celery_worker):
    """Full e2e test: home → input → submit → wait → verify results."""
    page.set_viewport_size({"width": 1920, "height": 1080})

    # 1. Land on home page
    page.goto(f"{BASE_URL}/")
    expect(page.locator(f"#{START_BUTTON_HOME_ID}")).to_be_visible(timeout=10000)
    wait_for_dash_callback(page)
    check_all_errors(page)
    logging.info("Home page loaded")

    # 2. Note the generated job_id
    job_input = page.locator(f"#{JOB_INPUT_HOME_ID}")
    expect(job_input).to_be_visible(timeout=5000)
    job_id = job_input.input_value()
    logging.info(f"Generated job_id: {job_id}")

    # 3. Click "Start" → arrives at /input/<job_id>
    page.locator(f"#{START_BUTTON_HOME_ID}").click()
    page.wait_for_url(f"**/input/{job_id}", timeout=10000)
    wait_for_dash_callback(page)
    check_all_errors(page)
    logging.info("Input page loaded")

    # 4. Upload sample CSV
    upload_area = page.locator(f"#{CSV_UPLOAD_INPUT_ID}")
    expect(upload_area).to_be_visible(timeout=5000)
    file_input = upload_area.locator("input[type='file']")
    file_input.set_input_files(SAMPLE_CSV)

    # Wait for upload feedback
    feedback = page.locator(f"#{UPLOAD_FEEDBACK_DIV_INPUT_ID}")
    expect(feedback).to_be_visible(timeout=10000)
    expect(feedback).to_contain_text("File uploaded")
    wait_for_dash_callback(page)
    logging.info("CSV uploaded successfully")

    # 5. Wait for "Check Input" to become enabled
    check_btn = page.locator(f"#{CHECK_INPUT_BUTTON_INPUT_ID}")
    expect(check_btn).to_be_enabled(timeout=5000)

    # 6. Click "Check Input" → arrives at /job-submission/<job_id>
    check_btn.click()
    page.wait_for_url(f"**/job-submission/{job_id}", timeout=10000)
    wait_for_dash_callback(page)
    check_all_errors(page)
    logging.info("Job submission page loaded")

    # 7. Verify input summary is shown (read-only accordion)
    expect(page.locator(f"#{ACCORDION_JOB_SUBMISSION_ID}")).to_be_visible(timeout=5000)

    # 8. Click "Submit Job"
    submit_btn = page.locator(f"#{SUBMIT_BUTTON_JOB_SUBMISSION_ID}")
    expect(submit_btn).to_be_enabled(timeout=5000)
    submit_btn.click()
    wait_for_dash_callback(page)
    logging.info("Job submitted")

    # 9. Wait for status to change to COMPLETED (poll via interval)
    status_div = page.locator(f"#{STATUS_DIV_JOB_SUBMISSION_ID}")
    max_wait = 60
    start = time.monotonic()
    while time.monotonic() - start < max_wait:
        page.wait_for_timeout(3000)
        status_text = status_div.text_content()
        if "COMPLETED" in status_text:
            logging.info("Job completed")
            break
        if "FAILED" in status_text:
            pytest.fail("Job failed unexpectedly")
    else:
        pytest.fail(f"Job did not complete within {max_wait}s")

    # 10. Verify accordion shows the job log, read from the database: the
    # worker writes no log file the web process could read
    expect(page.locator(f"#{ACCORDION_JOB_SUBMISSION_ID}")).to_be_visible(timeout=5000)
    expect(page.locator(f"#{JOB_LOGS_DIV_JOB_SUBMISSION_ID}")).to_contain_text(
        "saved to result.json", timeout=5000
    )

    # 11. Click "View Results" → arrives at /results/<job_id>
    results_btn = page.locator(f"#{VIEW_RESULTS_BUTTON_JOB_SUBMISSION_ID}")
    expect(results_btn).to_be_enabled(timeout=5000)
    results_btn.click()
    page.wait_for_url(f"**/results/{job_id}", timeout=10000)
    wait_for_dash_callback(page)
    check_all_errors(page)
    logging.info("Results page loaded")

    # 12. Verify summary table is populated
    expect(page.locator(f"#{SUMMARY_TABLE_RESULTS_ID}")).to_be_visible(timeout=15000)
    rows = page.locator(f"#{SUMMARY_TABLE_RESULTS_ID} .ag-row")
    expect(rows.first).to_be_visible(timeout=5000)
    row_count = rows.count()
    assert row_count >= 7, f"Expected at least 7 rows, got {row_count}"
    logging.info(f"Summary table has {row_count} rows")

    # 13. Verify charts are rendered
    charts = page.locator(".js-plotly-plot")
    expect(charts.first).to_be_visible(timeout=5000)
    logging.info(f"Found {charts.count()} rendered charts")

    # 14. Click "Back to Submission" → arrives at /job-submission/<job_id>
    back_btn = page.locator(f"#{BACK_BUTTON_RESULTS_ID}")
    expect(back_btn).to_be_visible(timeout=5000)
    back_btn.click()
    page.wait_for_url(f"**/job-submission/{job_id}", timeout=10000)
    wait_for_dash_callback(page)
    logging.info("Back to submission page")

    # 15. Verify download button is present
    expect(page.locator(f"#{DOWNLOAD_BUTTON_SHARED_ID}")).to_be_visible(timeout=5000)
    check_all_errors(page)
    logging.info("E2E test passed")


def test_error_recovery_flow(page, dash_app, celery_worker):
    """E2e test: trigger error → fail → change input → resubmit → complete."""
    page.set_viewport_size({"width": 1920, "height": 1080})

    # 1. Create job
    page.goto(f"{BASE_URL}/")
    expect(page.locator(f"#{START_BUTTON_HOME_ID}")).to_be_visible(timeout=10000)
    wait_for_dash_callback(page)
    job_id = page.locator(f"#{JOB_INPUT_HOME_ID}").input_value()
    page.locator(f"#{START_BUTTON_HOME_ID}").click()
    page.wait_for_url(f"**/input/{job_id}", timeout=10000)
    wait_for_dash_callback(page)
    logging.info(f"Created job {job_id}")

    # 2. Upload CSV
    upload_area = page.locator(f"#{CSV_UPLOAD_INPUT_ID}")
    expect(upload_area).to_be_visible(timeout=5000)
    upload_area.locator("input[type='file']").set_input_files(SAMPLE_CSV)
    feedback = page.locator(f"#{UPLOAD_FEEDBACK_DIV_INPUT_ID}")
    expect(feedback).to_contain_text("File uploaded", timeout=10000)
    wait_for_dash_callback(page)

    # 3. Enable "Trigger error" checkbox
    trigger_checkbox = page.locator(f"#{TRIGGER_ERROR_CHECKBOX_ID}")
    expect(trigger_checkbox).to_be_visible(timeout=5000)
    trigger_checkbox.check()
    wait_for_dash_callback(page)

    # 4. Check Input → Submit
    check_btn = page.locator(f"#{CHECK_INPUT_BUTTON_INPUT_ID}")
    expect(check_btn).to_be_enabled(timeout=5000)
    check_btn.click()
    page.wait_for_url(f"**/job-submission/{job_id}", timeout=10000)
    wait_for_dash_callback(page)

    submit_btn = page.locator(f"#{SUBMIT_BUTTON_JOB_SUBMISSION_ID}")
    expect(submit_btn).to_be_enabled(timeout=5000)
    submit_btn.click()
    wait_for_dash_callback(page)
    logging.info("Submitted with trigger_error=True")

    # 5. Wait for FAILED
    status_div = page.locator(f"#{STATUS_DIV_JOB_SUBMISSION_ID}")
    max_wait = 60
    start = time.monotonic()
    while time.monotonic() - start < max_wait:
        page.wait_for_timeout(3000)
        status_text = status_div.text_content()
        if "FAILED" in status_text:
            logging.info("Job failed as expected")
            break
    else:
        pytest.fail(f"Job did not fail within {max_wait}s")

    # 6. Click "Change Input" → confirmation modal appears (job is FAILED)
    change_btn = page.locator(f"#{CHANGE_INPUT_BUTTON_JOB_SUBMISSION_ID}")
    expect(change_btn).to_be_enabled(timeout=5000)
    change_btn.click()

    modal = page.locator(f"#{RESET_CONFIRM_MODAL_SHARED_ID}")
    expect(modal).to_be_visible(timeout=10000)
    page.locator(f"#{RESET_CONFIRM_BUTTON_SHARED_ID}").click()
    page.wait_for_url(f"**/input/{job_id}", timeout=10000)
    wait_for_dash_callback(page)

    # 7. File is pre-populated from job state — verify and disable "Trigger error"
    feedback = page.locator(f"#{UPLOAD_FEEDBACK_DIV_INPUT_ID}")
    expect(feedback).to_contain_text("File uploaded", timeout=10000)

    trigger_checkbox = page.locator(f"#{TRIGGER_ERROR_CHECKBOX_ID}")
    expect(trigger_checkbox).to_be_visible(timeout=5000)
    trigger_checkbox.uncheck()
    wait_for_dash_callback(page)

    # 8. Check Input → Resubmit (via modal)
    check_btn = page.locator(f"#{CHECK_INPUT_BUTTON_INPUT_ID}")
    expect(check_btn).to_be_enabled(timeout=5000)
    check_btn.click()
    page.wait_for_url(f"**/job-submission/{job_id}", timeout=10000)
    wait_for_dash_callback(page)

    # Job is now PENDING after reset — use Submit (not Resubmit)
    submit_btn = page.locator(f"#{SUBMIT_BUTTON_JOB_SUBMISSION_ID}")
    expect(submit_btn).to_be_enabled(timeout=5000)
    submit_btn.click()
    wait_for_dash_callback(page)
    logging.info("Submitted with trigger_error=False")

    # 9. Wait for COMPLETED
    start = time.monotonic()
    while time.monotonic() - start < max_wait:
        page.wait_for_timeout(3000)
        status_text = status_div.text_content()
        if "COMPLETED" in status_text:
            logging.info("Job completed after resubmit")
            break
        if "FAILED" in status_text:
            pytest.fail("Job failed on resubmit — should have succeeded")
    else:
        pytest.fail(f"Job did not complete within {max_wait}s")

    # 10. Verify results page loads
    results_btn = page.locator(f"#{VIEW_RESULTS_BUTTON_JOB_SUBMISSION_ID}")
    expect(results_btn).to_be_enabled(timeout=5000)
    results_btn.click()
    page.wait_for_url(f"**/results/{job_id}", timeout=10000)
    wait_for_dash_callback(page)
    expect(page.locator(f"#{SUMMARY_TABLE_RESULTS_ID}")).to_be_visible(timeout=15000)
    check_all_errors(page)
    logging.info("Error recovery e2e test passed")
