"""Guardrail: importing a framework module connects no signal.

Until the one-Celery-app change, ``background_job_manager`` connected
``worker_process_init`` at module level. Both apps then disconnected that
handler and connected their own, so the effective worker logging depended on
which module was imported last. The handler is now connected by the assembly
in ``cosmo_ecosystem.celery_app`` (see ``test_celery_app_assembly.py``).

Checked statically, like ``test_layouts.py`` does for callbacks: once a module
is imported, only its source can still tell whether the import was clean.
"""

import ast
import textwrap
from pathlib import Path

import pytest

import cosmo_ecosystem

PACKAGE_ROOT = Path(cosmo_ecosystem.__file__).parent


def _import_time_connects(source: str) -> list[str]:
    """``.connect`` calls and decorators that run when the module is imported.

    Function bodies run later and are skipped; their decorators, module-level
    statements and class bodies run at import and are searched.
    """
    offenders = []

    def visit(node):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                visit(decorator)
            return
        if isinstance(node, ast.Attribute) and node.attr == "connect":
            offenders.append(ast.unparse(node))
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(ast.parse(source))
    return offenders


@pytest.mark.parametrize(
    "source",
    [
        """
        @worker_process_init.connect
        def configure(**kwargs):
            pass
        """,
        """
        @signals.task_failure.connect(sender="x")
        def on_failure(**kwargs):
            pass
        """,
        """
        def configure(**kwargs):
            pass

        worker_process_init.connect(configure)
        """,
    ],
)
def test_the_check_catches_an_import_time_connect(source):
    assert _import_time_connects(textwrap.dedent(source)) != []


def test_the_check_ignores_a_connect_inside_a_function():
    """Connecting during a call, as the assembly does, is the allowed form."""
    source = """
    def assemble():
        worker_process_init.connect(configure, weak=False)
    """

    assert _import_time_connects(textwrap.dedent(source)) == []


def test_no_framework_module_connects_a_signal_at_import():
    offenders = {
        str(path.relative_to(PACKAGE_ROOT)): found
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        if (found := _import_time_connects(path.read_text()))
    }

    assert offenders == {}
