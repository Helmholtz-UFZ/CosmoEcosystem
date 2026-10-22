# Skill: Create a New Page

Step-by-step checklist for adding a new page to the Cosmo Ecosystem Dash application.

---

## 1. Clarification Questions

Ask the user before starting:

1. **Layout type** — Is this an **admin page** (column layout, like logs) or a **user-facing workflow page** (split layout with map, like user_info)?
2. **Route type** — Does it need a `job_id` (dynamic route `/job/<job_id>/my-page`) or a static route (`/my-page`)?
3. **Interactivity** — Does it need callbacks (interactive) or is it static content?
4. **Navbar** — Should it appear in the navbar?
5. **Error types** — Does it need custom error types?
6. **Tests** — Should Playwright tests be created?

---

## 2. Step-by-step Checklist

### Step 1: Create the page file

Create `src/pages/<page_name>.py`.

**Module docstring format:**

```python
"""Short description of what the page does.

# User documentation (This section is for user documentation and will appear in the user documentation.)

Detailed user-facing description of the page functionality.

# Notes (This section is for developer notes and will not appear in the user documentation.)

Developer notes about implementation details.
"""
```

**Import conventions** (top-level only, never inside functions):

```python
# 1. Standard library
import logging

# 2. Third-party
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, dcc, html, register_page
from dash.exceptions import PreventUpdate

# 3. Application
from src.constants.html_ids import (
    # ... only the IDs this page needs
)
from src.layout import (
    # ... only the layout helpers this page needs
)
```

**Register the page:**

```python
# Static route
register_page(
    __name__,
    path="/my-page",
    name="My Page",
    title="Cosmo Ecosystem - My Page",
    description="Brief description of the page.",
)

# OR dynamic route (with job_id)
register_page(
    __name__,
    path_template="/job/<job_id>/my-page",
    name="My Page",
    title="Cosmo Ecosystem - My Page",
    description="Brief description of the page.",
)
```

### Step 2: Choose layout pattern

| Pattern | Function | Use case | Reference |
|---------|----------|----------|-----------|
| Column | `page_container_column_layout(content)` | Admin/standalone pages | `pages/logs.py` |
| Split | `page_container_split_layout(map, input_container)` | Workflow pages with map (70/30) | `pages/user_info.py` |
| Fullscreen | `page_container_fullscreen_layout(content)` | Full-width content | `layout.py` |

All layout functions are in `src/layout.py`.

### Step 3: Build the layout function

**Static layout** (no dynamic data needed at load time):

```python
layout = page_container_column_layout([
    create_header("Title", "Subtitle", bg_color="bg-info", rounded=False),
    dbc.Container([
        # ... page content
    ], className="my-4"),
])
```

**Job files:** `Job(job_id)` reads the database row only, so it is cheap enough for
polls. A page that reads or writes the job's files first calls
`job_persistence.work_dir(job_id)` and uses the path it returns.

**Dynamic layout** (needs job state or computed values):

```python
def layout(job_id):  # or def layout(): for static-route dynamic content
    job = Job(job_id=job_id)
    status = job.get_status()
    is_active = status == JOB_STATUS_PENDING

    card_body = []

    # Add reset banner if not PENDING (workflow pages only)
    if not is_active:
        card_body.append(create_reset_banner(job_id, status))

    card_body.extend([
        # ... page-specific components
    ])

    # Add reset modal (workflow pages only)
    card_body.append(create_reset_modal())

    # Add job ID store (workflow pages only)
    card_body.append(dcc.Store(id=JOB_ID_STORE_SHARED_ID, data=job_id))

    footer = progress_footer(
        prev_url=build_url_step("previous_step", job_id),
        next_id=MY_NEXT_BUTTON_ID,
    )
    map = create_map(job=job)
    input_container = create_card_input(
        card_body,
        card_footer=footer,
        name_step=__name__.replace("pages.", ""),
        job_id=job_id,
    )

    return page_container_split_layout(map, input_container)
```

**Available layout helpers** from `src/layout.py`:
- `create_card_input(card_body, card_footer, name_step, title, job_id)` — card with optional progress tabs
- `create_header(title, subtitle, bg_color, id, rounded)` — page header. Leave
  `id` unset unless a callback writes into the header; it then stamps `id`,
  `{id}-title` and `{id}-subtitle`. Never pass `id=""` — that stamps three
  colliding ids shared by every header on the page.
- `progress_footer(prev_id, prev_url, next_id, next_url, ...)` — prev/next navigation footer
- `create_map(job, extra_layers)` — Leaflet map component
- `create_reset_banner(job_id, status)` — status banner with reset button (non-PENDING jobs)
- `create_reset_modal()` — reset confirmation modal

### Step 4: Global elements (automatic — do NOT recreate)

These are already in the global layout (`layout.py:app_layout()`). Do NOT add them to your page:

- **Loading overlay** — control via `LOADING_OVERLAY_SHARED_ID`
- **Error modal** — triggered automatically by `error_handling.py`
- **Navbar** — if your page needs a nav link, update `create_navbar()` in `layout.py` (see Step 11)
- **URL location** — `URL_SHARED_ID` is available globally

### Step 5: HTML IDs

File: `src/constants/html_ids.py`

**Only create IDs for:**
1. Components used in callbacks (Input/Output/State)
2. Components used in tests (Playwright locators)
3. Components used with `set_props()` (add `# nocheck`)
4. Dynamically constructed IDs (add `# nocheck`)

**Naming convention:** `<NAME>_<TYPE>_<PAGE>_ID`
- Example: `SUBMIT_BUTTON_MY_PAGE_ID = "submit-button-my-page-id"`

**Placement:** Add a new page section in alphabetical order:

```python
# ============================================================================
# PAGE: MY_PAGE
# ============================================================================

# --- Buttons ---
SUBMIT_BUTTON_MY_PAGE_ID = "submit-button-my-page-id"
```

**Resist over-creating IDs.** If a component is purely visual with no callback interaction and no test locator, it does not need an ID.

### Step 6: Error handling

File: `src/error_handling.py`

- Existing error modal handles uncaught exceptions automatically via `handle_error()`
- Only add a custom exception if you need a **specific user-facing message** for a new error type
- To add: create exception class + add entry to `error_responds_dict`

### Step 7: Callbacks

Place at the bottom of the page file, after the layout.

```python
# ============================================================================
# Callbacks
# ============================================================================


@callback(
    Output(MY_OUTPUT_ID, "property"),
    Input(MY_INPUT_ID, "property"),
    State(MY_STATE_ID, "property"),
    prevent_initial_call=True,
)
def my_callback(input_value, state_value):
    """Describe what this callback does."""
    if not input_value:
        raise PreventUpdate
    # ... logic
    return result
```

**Patterns:**
- Use `prevent_initial_call=True` unless the callback should fire on page load
- Use `PreventUpdate` for guard clauses
- Use `allow_duplicate=True` on outputs shared with other callbacks
- See `docs/conventions/callbacks.md` for full patterns

### Step 8: Styling

- **Bootstrap classes ONLY** — no `style={}` dicts
- Reference: `docs/conventions/bootstrap_styling.md`

### Step 9: Logging

```python
log = logging.getLogger(__name__)
```

- Use `log.info()`, `log.debug()`, `log.warning()`, `log.error()`
- **DO NOT** use `extra={"tag": ...}`
- See `docs/conventions/logging.md`

### Step 10: Documentation (auto-generated web docs)

After the page works:

```bash
python -m src.doc_generator <job_id>
```

This captures a screenshot and extracts the module docstring into web documentation. Ensure your `# User documentation` section in the docstring is complete.

### Step 11: Navbar (if applicable)

File: `src/layout.py`, function `create_navbar()`

Add a `dbc.NavItem` inside the `dbc.Nav` children list:

```python
dbc.NavItem(
    dbc.NavLink(
        "My Page",
        href=dash.page_registry["pages.my_page"]["relative_path"],
    )
),
```

### Step 12: Testing (if requested)

Add a Playwright test in `test/`.

- Use HTML ID constants for locators: `f"#{MY_COMPONENT_ID}"`
- Run: `./run_pytest.sh`
- Run headed: `./run_pytest.sh --headed`
- Generate test skeleton: `./run_codegen_test.sh`
- See `docs/conventions/testing.md`

### Step 13: Verify all tests pass

```bash
./run_pytest.sh
```

Always run the full test suite to confirm no regressions.

---

## 3. Reference Templates

### Admin page (column layout, like `pages/logs.py`)

```python
"""Short description.

# User documentation (This section is for user documentation and will appear in the user documentation.)

User-facing description.

# Notes (This section is for developer notes and will not appear in the user documentation.)

Developer notes.
"""

import logging

import dash_bootstrap_components as dbc
from dash import Input, Output, callback, html, register_page

from src.constants.html_ids import (
    # page-specific IDs
)
from src.layout import create_header, page_container_column_layout

log = logging.getLogger(__name__)

register_page(
    __name__,
    path="/my-page",
    name="My Page",
    title="Cosmo Ecosystem - My Page",
    description="Brief description.",
)

layout = page_container_column_layout([
    create_header("Title", "Subtitle", bg_color="bg-info", rounded=False),
    dbc.Container([
        # page content here
    ], className="my-4"),
])


# ============================================================================
# Callbacks
# ============================================================================


@callback(
    Output(...),
    Input(...),
    prevent_initial_call=True,
)
def my_callback(...):
    """Callback description."""
    ...
```

### Workflow page (split layout, like `pages/user_info.py`)

```python
"""Short description.

# User documentation (This section is for user documentation and will appear in the user documentation.)

User-facing description.

# Notes (This section is for developer notes and will not appear in the user documentation.)

Developer notes.
"""

import logging

import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, dcc, html, register_page
from dash.exceptions import PreventUpdate

from src.constants.general import JOB_STATUS_PENDING
from src.constants.html_ids import (
    JOB_ID_STORE_SHARED_ID,
    URL_SHARED_ID,
    # page-specific IDs
)
from src.job import Job
from src.layout import (
    build_url_step,
    create_card_input,
    create_map,
    create_reset_banner,
    create_reset_modal,
    page_container_split_layout,
    progress_footer,
)

log = logging.getLogger(__name__)

register_page(
    __name__,
    path_template="/job/<job_id>/my-page",
    name="My Page",
    title="Cosmo Ecosystem - My Page",
    description="Brief description.",
)


def layout(job_id):
    job = Job(job_id=job_id)
    status = job.get_status()
    is_active = status == JOB_STATUS_PENDING

    card_body = []

    if not is_active:
        card_body.append(create_reset_banner(job_id, status))

    card_body.extend([
        # page-specific form components here
    ])

    card_body.append(create_reset_modal())
    card_body.append(dcc.Store(id=JOB_ID_STORE_SHARED_ID, data=job_id))

    footer = progress_footer(
        prev_url=build_url_step("previous_step", job_id),
        next_id=MY_NEXT_BUTTON_ID,
    )
    map = create_map(job=job)
    input_container = create_card_input(
        card_body,
        card_footer=footer,
        name_step=__name__.replace("pages.", ""),
        job_id=job_id,
    )

    return page_container_split_layout(map, input_container)


# ============================================================================
# Callbacks
# ============================================================================


@callback(
    Output(URL_SHARED_ID, "pathname", allow_duplicate=True),
    Input(MY_NEXT_BUTTON_ID, "n_clicks"),
    State(URL_SHARED_ID, "pathname"),
    prevent_initial_call=True,
)
def go_to_next_page(n_clicks, pathname):
    """Navigate to next step."""
    if not n_clicks or not pathname:
        raise PreventUpdate
    job_id = pathname.split("/")[2]
    return build_url_step("next_step", job_id)
```

---

## 4. Key File References

| File | Purpose |
|------|---------|
| `src/pages/<page_name>.py` | The new page (create) |
| `src/constants/html_ids.py` | HTML ID constants (edit) |
| `src/layout.py` | Layout helpers + navbar (edit if adding nav link) |
| `src/error_handling.py` | Custom exceptions (edit if new error types) |
| `docs/conventions/callbacks.md` | Callback patterns reference |
| `docs/conventions/bootstrap_styling.md` | Styling reference |
| `docs/conventions/html_ids.md` | ID naming reference |
| `docs/conventions/testing.md` | Test execution reference |
| `docs/conventions/logging.md` | Logging patterns reference |
