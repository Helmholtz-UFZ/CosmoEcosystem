"""app.py must not start a thread, nor Celery Beat.

Gunicorn with --preload imports app.py once and forks its workers from that
process. A thread running at that moment can hold one of Celery's internal locks,
and the forked worker then blocks forever on its first task submission — no error,
no log line, just a request that never returns. Without --preload every worker
imports app.py, and a Beat started there runs once per worker. Beat belongs in the
Celery worker (``--beat``); see docs/conventions/celery_beat.md in cosmo-ecosystem.

Read from the source: importing app.py would boot the whole app.
"""

import ast
from pathlib import Path

APP = Path(__file__).parent.parent / "csv_profiler" / "app.py"

# Everything that starts concurrent work; `Beat` covers `celery_app.Beat(...)`.
FORBIDDEN_CALLS = {"Thread", "Timer", "ThreadPoolExecutor", "Beat"}


def _is_main_guard(statement):
    """`if __name__ == "__main__":` — never runs under Gunicorn."""
    return (
        isinstance(statement, ast.If)
        and isinstance(statement.test, ast.Compare)
        and isinstance(statement.test.left, ast.Name)
        and statement.test.left.id == "__name__"
    )


def _called_names(tree):
    """Names of everything app.py calls, the __main__ block left out."""
    for statement in tree.body:
        if _is_main_guard(statement):
            continue
        for node in ast.walk(statement):
            if isinstance(node, ast.Call):
                func = node.func
                yield (
                    func.attr
                    if isinstance(func, ast.Attribute)
                    else getattr(func, "id", None)
                )


def test_app_starts_no_thread():
    offenders = sorted(set(_called_names(ast.parse(APP.read_text()))) & FORBIDDEN_CALLS)

    assert not offenders, (
        f"{APP.name} calls {offenders}; run it in the Celery worker instead "
        "(cosmo-ecosystem docs/conventions/celery_beat.md)"
    )
