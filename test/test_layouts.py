"""Tests for the seams in ``cosmo_ecosystem.layouts``.

Three of them, all covering things that fail without a word:

- the page-wrapper fallback. The three framework pages call
  ``page_container_column_layout`` themselves, so a consumer has no call site to
  pass ``wrapper_class`` at. Without the module-level fallback the only hook left
  is ``#main-content-container``, and COSMONAUT had to key its stylesheet on that
  framework-internal id.
- ``create_header``'s optional id. Both apps carried a local copy defaulting to
  ``id=""``, which stamped colliding ids on every header built without one.
- the navbar callback, which used to register itself on import.

Plus what left in v0.13.0: the job reset and ``create_job_header``, the two
pieces bound to the concrete ``Job``.
"""

import ast
from pathlib import Path

import dash
import pytest
from dash import html

from cosmo_ecosystem import constants, layouts
from cosmo_ecosystem.constants import NAVBAR_COLLAPSE_DIV_SHARED_ID


@pytest.fixture(autouse=True)
def reset_wrapper_class():
    """Restore the module seam — it is process-global state."""
    yield
    layouts.default_wrapper_class = None


def test_no_wrapper_div_by_default():
    """An app that sets nothing gets exactly the DOM it got before."""
    page = layouts.page_container_column_layout([])

    assert page.className == "flex-grow-1 d-flex justify-content-center g-0"


def test_module_default_wraps_pages_built_without_an_argument():
    """This is the case the three framework pages are in."""
    layouts.default_wrapper_class = "cosmonaut-page"

    page = layouts.page_container_column_layout([])

    assert page.className == "cosmonaut-page"


def test_explicit_argument_beats_the_module_default():
    """A caller that does have a call site keeps control."""
    layouts.default_wrapper_class = "cosmonaut-page"

    page = layouts.page_container_column_layout([], wrapper_class="w-100")

    assert page.className == "w-100"


def test_landing_page_layout_column_uses_the_module_default():
    """The seam reaches the landing-page helper the domain pages build on."""
    layouts.default_wrapper_class = "cosmonaut-page"

    page = layouts.landing_page_layout_column(
        "Job Submission",
        "header-div",
        "job-id-store",
        "quiet_amber_otter",
        "main-content",
    )

    assert page.className == "cosmonaut-page"


# ---------------------------------------------------------------------------
# create_header: ids only when asked for
# ---------------------------------------------------------------------------


def test_create_header_stamps_no_id_by_default():
    """The default must stamp nothing — this is the bug both apps had.

    Their local copies defaulted to ``id=""``, so every header built without an
    id carried ``""``, ``"-title"`` and ``"-subtitle"``. Three ids, shared by
    every header on the page, and duplicate ids are not something Dash reports.
    """
    header = layouts.create_header("Job Submission", "quiet_amber_otter")

    assert not hasattr(header, "id")
    assert not any(hasattr(child, "id") for child in header.children)


def test_create_header_stamps_all_three_when_given_an_id():
    """The three handles COSMOPOLITAN's hydration callbacks write into."""
    header = layouts.create_header("Job Submission", "quiet_amber_otter", id="x")

    assert header.id == "x"
    title, subtitle = header.children
    assert title.id == "x-title"
    assert subtitle.id == "x-subtitle"


def test_create_header_without_subtitle_has_no_subtitle_element():
    """An empty subtitle leaves the H3 out, id or no id."""
    plain = layouts.create_header("Job not found", "")
    with_id = layouts.create_header("Job not found", "", id="x")

    assert len(plain.children) == 1
    assert len(with_id.children) == 1
    assert with_id.children[0].id == "x-title"


def test_create_header_id_is_keyword_only_in_practice():
    """``bg_color`` and ``rounded`` keep their meaning at every call site.

    ``id`` was inserted before ``rounded``, which is safe only because no caller
    passes ``rounded`` positionally. Pinned so that a later parameter does not
    get slipped in ahead of one that *is* passed positionally.
    """
    header = layouts.create_header("Title", "Sub", "bg-danger", rounded=False)

    assert header.className == "bg-danger py-2"
    assert not hasattr(header, "id")


# ---------------------------------------------------------------------------
# The navbar callback: registered on request, not on import
# ---------------------------------------------------------------------------


def test_layouts_registers_no_callback_at_import():
    """A library module must not put a callback into a consumer's registry.

    ``cosmo_ecosystem.layouts`` is imported by every framework page, so a
    module-level ``@callback`` here reaches every app that imports any page.
    COSMOPOLITAN's navbar worked purely as a side effect of that; COSMONAUT got
    a callback bound to an id it never mounts. Both silent, in opposite
    directions.

    Checked statically rather than through the registry: the import has already
    happened by the time this test runs, so only the source can still tell us
    whether it was clean.
    """
    tree = ast.parse(Path(layouts.__file__).read_text())

    offenders = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            offenders += [
                node.name
                for decorator in node.decorator_list
                if _is_callback_call(decorator)
            ]
        if isinstance(node, ast.Expr) and _is_callback_call(node.value):
            offenders.append(ast.unparse(node.value.func))

    assert offenders == []


def _is_callback_call(node):
    """Is this AST node a ``@callback`` / ``dash.clientside_callback`` call?"""
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr in ("callback", "clientside_callback")
    return isinstance(func, ast.Name) and func.id == "callback"


@pytest.fixture
def clean_navbar_registration():
    """Undo the navbar registration — the Dash callback map is process-global."""
    key = f"{NAVBAR_COLLAPSE_DIV_SHARED_ID}.is_open"
    yield key
    layouts._navbar_callbacks_registered = False
    dash._callback.GLOBAL_CALLBACK_MAP.pop(key, None)
    dash._callback.GLOBAL_CALLBACK_LIST[:] = [
        entry for entry in dash._callback.GLOBAL_CALLBACK_LIST if entry["output"] != key
    ]


def test_register_navbar_callbacks_registers_the_toggle(clean_navbar_registration):
    """The behaviour the import used to provide is still available on request."""
    key = clean_navbar_registration
    assert key not in dash._callback.GLOBAL_CALLBACK_MAP

    layouts.register_navbar_callbacks()

    assert key in dash._callback.GLOBAL_CALLBACK_MAP


def test_register_navbar_callbacks_is_idempotent(clean_navbar_registration):
    """A second call is a no-op, not a DuplicateCallback.

    An app may reach the registration from more than one place — through
    ``app_layout`` and directly, say.
    """
    layouts.register_navbar_callbacks()
    layouts.register_navbar_callbacks()

    assert clean_navbar_registration in dash._callback.GLOBAL_CALLBACK_MAP


@pytest.fixture
def stub_navbar(monkeypatch):
    """Stand in for ``create_navbar``, which needs an app to draw itself.

    It resolves the three framework pages out of ``dash.page_registry`` and asks
    ``dash.get_relative_path`` for the brand href; a bare test process has
    neither, and ``requests_pathname_prefix`` turns read-only as soon as any
    test in the suite constructs a ``Dash``. None of that is what these two
    tests are about — the question is whether ``app_layout`` *wires* the navbar,
    not how it draws one.
    """
    monkeypatch.setattr(layouts, "create_navbar", lambda: html.Div())


def test_app_layout_registers_the_navbar_callback(
    stub_navbar, clean_navbar_registration
):
    """The function that mounts the navbar wires it, in the same call.

    Co-location, not a hidden side effect: the defect this batch fixed was an
    *import* registering a callback, not a function registering the callback for
    the component it unconditionally mounts. The navbar is not optional —
    every layout this builds has one — so there is no call in which the
    registration is unwanted, and no consumer of ``app_layout`` can lose its
    toggle by re-pinning without noticing.
    """
    assert clean_navbar_registration not in dash._callback.GLOBAL_CALLBACK_MAP

    layouts.app_layout()

    assert clean_navbar_registration in dash._callback.GLOBAL_CALLBACK_MAP


def test_app_layout_twice_does_not_duplicate_the_callback(
    stub_navbar, clean_navbar_registration
):
    """``app.layout`` may be a callable Dash invokes per request."""
    layouts.app_layout()
    layouts.app_layout()

    assert clean_navbar_registration in dash._callback.GLOBAL_CALLBACK_MAP


def test_layouts_does_not_import_the_concrete_job():
    """Job reset and the job header moved to the example; nothing here needs ``Job``.

    The framework must stay bindable to any ``BaseJob``: a ``Job`` import in
    ``layouts`` drags the concrete class into every app that imports a page.
    """
    tree = ast.parse(Path(layouts.__file__).read_text())

    job_imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "cosmo_ecosystem.job"
    ]

    assert job_imports == []


def test_app_layout_has_no_reset_option(stub_navbar, clean_navbar_registration):
    """``with_reset`` is gone (v0.13.0); an app mounts its own reset, if any."""
    with pytest.raises(TypeError):
        layouts.app_layout(with_reset=True)


def test_framework_ships_no_reset_ids():
    """The ``RESET_*`` ids belong to the app that mounts the reset modal."""
    from_constants = [name for name in dir(constants) if name.startswith("RESET_")]

    assert from_constants == []
