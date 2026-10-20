"""Collection of layout components for the web application."""

import dash
import dash_bootstrap_components as dbc
import logging

from dash import Input, Output, State, callback, callback_context, dcc, html

from cosmo_ecosystem.constants import (
    LOADING_OVERLAY_MODAL_SHARED_ID,
    NAVBAR_COLLAPSE_DIV_SHARED_ID,
    NAVBAR_TOGGLER_BUTTON_SHARED_ID,
    RESET_BODY_DIV_SHARED_ID,
    RESET_CANCEL_BUTTON_SHARED_ID,
    RESET_CONFIRM_BUTTON_SHARED_ID,
    RESET_CONFIRM_MODAL_SHARED_ID,
    RESET_JOB_STORE_SHARED_ID,
    URL_LOCATION_SHARED_ID,
)
from cosmo_ecosystem.error_handling import error_modal
from cosmo_ecosystem.job import Job

reset_confirm_modal = dbc.Modal(
    [
        dbc.ModalHeader("Confirm Reset"),
        dbc.ModalBody(id=RESET_BODY_DIV_SHARED_ID),
        dbc.ModalFooter(
            [
                dbc.Button(
                    "Cancel",
                    id=RESET_CANCEL_BUTTON_SHARED_ID,
                    color="secondary",
                ),
                dbc.Button(
                    "Confirm",
                    id=RESET_CONFIRM_BUTTON_SHARED_ID,
                    color="danger",
                ),
            ]
        ),
    ],
    id=RESET_CONFIRM_MODAL_SHARED_ID,
    is_open=False,
    centered=True,
)

loading_overlay = dbc.Modal(
    dbc.ModalBody(
        [dbc.Spinner(size="lg"), html.H4("Loading...", className="text-center mt-3")],
        className="text-center",
    ),
    id=LOADING_OVERLAY_MODAL_SHARED_ID,
    is_open=False,
    backdrop="static",
    keyboard=False,
    centered=True,
    size="sm",
)


def app_layout(with_reset=False):
    """Create the main page layout with navbar and content.

    Registers the navbar-collapse callback, because it mounts the navbar. The
    two belong together: a function that puts a component on the page and wires
    that same component is co-location, not a side effect. What must never
    happen is an *import* doing it — see ``register_navbar_callbacks``.

    Note the asymmetry with ``with_reset``, which is deliberate. The reset modal
    is optional, so registering its callbacks unasked would put a feature into a
    consumer's process that it never wanted. The navbar is not optional: every
    layout this function builds has one, so there is no call in which the
    callback is unwanted.

    Args:
        with_reset: Include the job-reset confirmation modal and register its
            callbacks. Opt-in, because an app that offers no reset action would
            otherwise carry two callbacks that can never fire — the framework
            must not put a feature into a consumer's process uninvited. An app
            that opts in triggers the modal by writing
            ``{"job_id": …, "action": "resubmit"|"reset"}`` into
            RESET_JOB_STORE_SHARED_ID.
    """
    register_navbar_callbacks()

    children = [
        dcc.Location(id=URL_LOCATION_SHARED_ID, refresh=True),
        error_modal,
        create_navbar(),
        dash.page_container,
        loading_overlay,
    ]

    if with_reset:
        register_reset_callbacks()
        children += [reset_confirm_modal, dcc.Store(id=RESET_JOB_STORE_SHARED_ID)]

    return html.Div(
        className="d-flex flex-column min-vh-100 bg-light",
        children=children,
    )


def create_navbar():
    """Create a navbar layout."""
    return html.Nav(
        className="navbar navbar-expand-lg sticky-top navbar-dark bg-primary",
        children=[
            dbc.Container(
                children=[
                    dbc.NavbarBrand(
                        # Index route — the active domain registers the page at "/".
                        href=dash.get_relative_path("/"),
                        children=[
                            html.Img(
                                src="/static/icon_navbar.svg",
                                width="30",
                                height="30",
                                className="d-inline-block align-text-top",
                                alt="Cosmo Ecosystem Icon",
                            ),
                            " Cosmo Ecosystem",
                        ],
                    ),
                    dbc.NavbarToggler(id=NAVBAR_TOGGLER_BUTTON_SHARED_ID),
                    dbc.Collapse(
                        dbc.Nav(
                            className="navbar-nav me-auto mb-2 mb-lg-0",
                            children=[
                                dbc.NavItem(
                                    dbc.NavLink(
                                        [
                                            html.I(className="bi bi-list-task me-1"),
                                            "Job Management",
                                        ],
                                        href=dash.page_registry["pages.job_management"][
                                            "relative_path"
                                        ],
                                    )
                                ),
                                dbc.NavItem(
                                    dbc.NavLink(
                                        [
                                            html.I(className="bi bi-cpu me-1"),
                                            "Worker Management",
                                        ],
                                        href=dash.page_registry[
                                            "pages.worker_management"
                                        ]["relative_path"],
                                    )
                                ),
                                dbc.NavItem(
                                    dbc.NavLink(
                                        [
                                            html.I(className="bi bi-journal-text me-1"),
                                            "Logs",
                                        ],
                                        href=dash.page_registry["pages.logs"][
                                            "relative_path"
                                        ],
                                    )
                                ),
                            ],
                        ),
                        id=NAVBAR_COLLAPSE_DIV_SHARED_ID,
                        navbar=True,
                    ),
                ]
            )
        ],
    )


# Dash raises DuplicateCallback if the same callback is registered twice, and an
# app may call the registration from more than one place. Same guard as
# `_reset_callbacks_registered` further down.
_navbar_callbacks_registered = False


def register_navbar_callbacks():
    """Register the navbar-collapse toggle (idempotent).

    ``app_layout`` calls this for you. It is public for the app that mounts
    NAVBAR_COLLAPSE_DIV_SHARED_ID in a navbar of its own and never calls
    ``app_layout`` — COSMOPOLITAN's case, and the reason this is a function
    rather than a line inside ``app_layout``.

    Until v0.6.2 the callback sat at module level, so the mere
    ``import cosmo_ecosystem.layouts`` that every framework page performs registered
    it. That made it invisible in both directions:

    - COSMOPOLITAN mounts the framework id in its own navbar and has no callback
      of its own. Its toggle worked purely as a side effect of that import — and
      would have died without a word the day it stopped importing a framework
      page.
    - COSMONAUT mounts a different id and registers its own callback. The
      framework's was registered against an id that is never on the page: dead
      weight in the registry, equally silent.

    Neither is an error Dash can report. The rule the fix follows is narrow: an
    *import* must not register application behaviour. A function that mounts the
    component and wires it in the same breath is fine, which is why
    ``app_layout`` calls this and why nothing here is opt-in. See
    docs/conventions/framework_page_imports.md.
    """
    global _navbar_callbacks_registered
    if _navbar_callbacks_registered:
        return
    _navbar_callbacks_registered = True

    @callback(
        Output(NAVBAR_COLLAPSE_DIV_SHARED_ID, "is_open"),
        [Input(NAVBAR_TOGGLER_BUTTON_SHARED_ID, "n_clicks")],
        [State(NAVBAR_COLLAPSE_DIV_SHARED_ID, "is_open")],
        prevent_initial_call=True,
    )
    def toggle_navbar_collapse(n_clicks, is_open):
        """Toggle the navbar collapse state."""
        if n_clicks:
            return not is_open
        return is_open


JOB_STATUS_COLORS = {
    "PENDING": "bg-info",
    "RUNNING": "bg-warning",
    "FAILED": "bg-danger",
    "COMPLETED": "bg-success",
}


def create_header(title, subtitle, bg_color="bg-info", id=None, rounded=True):
    """Create a header layout.

    Args:
        title: Text of the H2.
        subtitle: Text of the H3; an empty string leaves the element out.
        bg_color: Bootstrap background class for the wrapping div.
        id: When given, stamps ``id`` on the div, ``{id}-title`` on the H2 and
            ``{id}-subtitle`` on the H3 — the three handles COSMOPOLITAN's
            hydration callbacks write into. When ``None``, **no ids are stamped
            at all**, which is what every framework page needs.

            There is deliberately no default id. The local copies both apps
            carried defaulted to ``id=""`` and therefore stamped the colliding
            ``""``, ``"-title"`` and ``"-subtitle"`` on every header built
            without one; COSMONAUT deleted its copy over exactly that. An empty
            id is not "no id", it is a duplicate id shared by every header on
            the page.
        rounded: Round the top corners.

    ``id`` shadows the builtin. Renaming it would break the call sites this
    parameter exists to serve, and no builtin ``id()`` is used in this module.
    """
    className = f"{bg_color} rounded-top py-2" if rounded else f"{bg_color} py-2"

    def id_kwargs(suffix):
        """Return the ``id=`` kwargs for one element, empty when no id is set."""
        return {} if id is None else {"id": f"{id}{suffix}"}  # nocheck - dynamic

    children = [html.H2(title, className="text-center", **id_kwargs("-title"))]
    if subtitle != "":
        children.append(
            html.H3(subtitle, className="text-center", **id_kwargs("-subtitle"))
        )
    return html.Div(className=className, children=children, **id_kwargs(""))


def create_job_header(title, job):
    """Create a header for job pages, colored by job status."""
    bg_color = JOB_STATUS_COLORS[job.status]
    return create_header(title, job.model.job_id, bg_color=bg_color)


def job_not_found_layout(job_id):
    """Return header and body for a job that cannot be loaded."""
    header = create_header("Job not found", job_id, bg_color="bg-danger")
    body = html.Div(f"Job not found: {job_id}", className="text-center m-3")
    return header, body


def landing_page_layout_column(
    header_title, header_id, job_id_store, job_id, main_content_id, wrapper_class=None
):
    """Create a landing page layout for a given job ID.

    ``wrapper_class`` is passed through to page_container_column_layout; leaving
    it at ``None`` falls back to ``default_wrapper_class``.
    """
    header = create_header(header_title, "Loading ...", bg_color="bg-secondary")

    content = [
        dcc.Store(id=job_id_store, data=job_id),  # nocheck
        html.Div(header, id=header_id),  # nocheck
        html.Div(
            html.Div(
                dbc.Spinner(
                    size="lg",
                    color="primary",
                    type="border",
                    fullscreen=False,
                ),
                className="d-flex justify-content-center align-items-center flex-grow-1",  # noqa
            ),
            id=main_content_id,  # nocheck
            className="flex-grow-1 d-flex flex-column",
        ),
    ]
    return page_container_column_layout(content, wrapper_class=wrapper_class)


# Seam: the wrapper class every page container falls back to. An app sets it
# BEFORE importing the framework pages — `pages/job_management.py` builds its
# `layout` at import time, so a value set afterwards would miss that page and
# only that page. Same rule as the `Job` class attributes: configure the seam,
# then import. See docs/conventions/framework_page_imports.md.
#
#     import cosmo_ecosystem.layouts
#     cosmo_ecosystem.layouts.default_wrapper_class = "cosmonaut-page"
#     import cosmo_ecosystem.pages.job_management  # noqa: E402
#
# Assign the module attribute; a `from … import default_wrapper_class` binds a
# copy of the value and configures nothing.
default_wrapper_class = None


def page_container_column_layout(
    content, main_content_id="main-content-container", wrapper_class=None
):
    """Create a page container with a single column layout.

    Args:
        content: Children of the content column.
        main_content_id: HTML id of the content column.
        wrapper_class: Bootstrap classes for an enclosing div. An app whose
            shell puts pages next to something else — COSMONAUT renders a map
            beside them — needs a marker class it can select on to give these
            pages the full width. Without it the only hook is
            ``#main-content-container``, which forces the app to key its CSS on
            a framework-internal id.

            ``None`` means "use ``default_wrapper_class``", which is itself
            ``None`` unless an app sets it — so by default the DOM is unchanged.
            The fallback lives here rather than in each caller because the three
            framework pages build their own layout and call this function
            themselves: a consumer has no call site to pass an argument at.
    """
    if wrapper_class is None:
        wrapper_class = default_wrapper_class

    class_names_content = "col-md-11 col-lg-10 col-xl-9 bg-white border border-dark rounded p-0 mb-4 mt-2 d-flex flex-column"  # noqa
    page = dbc.Row(
        dbc.Col(
            className=class_names_content,
            children=content,
            id=main_content_id,  # nocheck
        ),
        className="flex-grow-1 d-flex justify-content-center g-0",
    )
    if wrapper_class is not None:
        return html.Div(page, className=wrapper_class)
    return page


log = logging.getLogger(__name__)


# Dash raises DuplicateCallback if the same callback is registered twice, and
# `app.layout` may legitimately be a callable that Dash invokes per request.
# Hence a registration guard rather than a plain call.
_reset_callbacks_registered = False


def register_reset_callbacks():
    """Register the job-reset callbacks (idempotent).

    Called by ``app_layout(with_reset=True)``; call it directly only when
    building a layout by hand rather than through ``app_layout``.
    """
    global _reset_callbacks_registered
    if _reset_callbacks_registered:
        return
    _reset_callbacks_registered = True

    @callback(
        Output(RESET_CONFIRM_MODAL_SHARED_ID, "is_open", allow_duplicate=True),
        Output(RESET_BODY_DIV_SHARED_ID, "children"),
        Input(RESET_JOB_STORE_SHARED_ID, "data"),
        prevent_initial_call=True,
    )
    def open_reset_modal(store_data):
        """Open the reset confirmation modal when the store receives data."""
        if store_data is None:
            return False, dash.no_update
        if store_data["action"] == "resubmit":
            msg = (
                "This will reset the job to PENDING, delete all results, and resubmit."  # noqa
            )
        else:
            msg = "This will reset the job to PENDING and delete all results."
        return True, msg

    @callback(
        Output(RESET_CONFIRM_MODAL_SHARED_ID, "is_open", allow_duplicate=True),
        Output(URL_LOCATION_SHARED_ID, "href", allow_duplicate=True),
        Output(RESET_JOB_STORE_SHARED_ID, "data", allow_duplicate=True),
        Output(LOADING_OVERLAY_MODAL_SHARED_ID, "is_open", allow_duplicate=True),
        Input(RESET_CONFIRM_BUTTON_SHARED_ID, "n_clicks"),
        Input(RESET_CANCEL_BUTTON_SHARED_ID, "n_clicks"),
        State(RESET_JOB_STORE_SHARED_ID, "data"),
        prevent_initial_call=True,
    )
    def handle_reset_confirm(confirm_clicks, cancel_clicks, store_data):
        """Handle confirm/cancel on the reset modal."""
        triggered_ids = {
            t["prop_id"].split(".")[0]
            for t in callback_context.triggered
            if t["value"] is not None
        }

        if RESET_CANCEL_BUTTON_SHARED_ID in triggered_ids:
            return False, dash.no_update, None, dash.no_update

        if RESET_CONFIRM_BUTTON_SHARED_ID in triggered_ids:
            job = Job(job_id=store_data["job_id"])
            job.reset()

            if store_data["action"] == "resubmit":
                job.submit()
                path = f"/job-submission/{job.job_id}"
            else:
                path = f"/input/{job.job_id}"

            return False, path, None, False

        return (
            dash.no_update,
            dash.no_update,
            dash.no_update,
            dash.no_update,
        )
