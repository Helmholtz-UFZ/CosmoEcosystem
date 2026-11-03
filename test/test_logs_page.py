"""The logs page's default time windows, around midnight in particular.

The page shows one date and an hour:minute range on it, so a window that would
start on the previous day has to stop at that day's start instead.
"""

import importlib
from datetime import datetime, timedelta

import dash
import pytest

PAGE_MODULE = "cosmo_ecosystem.pages.logs"
JUST_AFTER_MIDNIGHT = datetime(2026, 11, 3, 0, 30)
AT_MIDNIGHT = datetime(2026, 11, 3, 0, 0, 12)
MIDDAY = datetime(2026, 11, 3, 12, 30)


@pytest.fixture(scope="module")
def logs():
    dash.Dash(__name__, use_pages=True, pages_folder="")
    return importlib.import_module(PAGE_MODULE)


def _start_and_end(logs, now, span):
    start, end = logs.default_window(now, span)
    return (start.hour, start.minute), (end.hour, end.minute)


def test_the_window_is_the_span_before_now_at_midday(logs):
    assert _start_and_end(logs, MIDDAY, timedelta(hours=1)) == ((11, 30), (12, 30))
    assert _start_and_end(logs, MIDDAY, timedelta(minutes=5)) == ((12, 25), (12, 30))


def test_the_window_stops_at_midnight_instead_of_wrapping_to_the_evening(logs):
    """00:30 minus an hour is 23:30 yesterday; the page can only show today."""
    assert _start_and_end(logs, JUST_AFTER_MIDNIGHT, timedelta(hours=1)) == (
        (0, 0),
        (0, 30),
    )
    assert _start_and_end(
        logs, JUST_AFTER_MIDNIGHT.replace(minute=3), timedelta(minutes=5)
    ) == ((0, 0), (0, 3))


@pytest.mark.parametrize("now", [JUST_AFTER_MIDNIGHT, AT_MIDNIGHT])
@pytest.mark.parametrize("span", [timedelta(hours=1), timedelta(minutes=5)])
def test_the_default_window_never_reads_as_start_after_end(
    logs, monkeypatch, now, span
):
    """The error the page showed between 00:00 and 01:00."""
    monkeypatch.setattr(logs.DbManager, "query_logs", lambda *args: [])
    start, end = logs.default_window(now, span)

    _, _, error, _ = logs._query_and_format(
        str(now.date()),
        start.hour,
        start.minute,
        end.hour,
        end.minute,
        ["INFO"],
        [],
        None,
        [],
    )

    assert error == ""
