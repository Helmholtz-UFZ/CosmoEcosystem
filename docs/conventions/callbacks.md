# Callback Conventions

## Callback Types

### Page-Specific Callbacks
Use `@callback` decorator in page files. Auto-registered via Dash pages plugin.

```python
# In pages/user_info.py
from dash import callback, Input, Output

@callback(
    Output(SOME_INPUT_ID, "valid"),
    Output(SOME_INPUT_ID, "invalid"),
    Input(SOME_INPUT_ID, "value"),
)
def validate_input(value):
    ...
```

### Shared Callbacks
Wrap them in a `register_*_callbacks()` function. Never register a callback at
module level: the app then inherits it from a bare `import`, and a callback
nobody asked for fails in ways Dash cannot report — see
[framework page imports](framework_page_imports.md#4-an-import-registers-a-callback-and-a-consumer-never-asked)
for the two shapes that failure took in the two apps.

Who calls the function depends on the component. A layout function that mounts
the component **unconditionally** calls it itself — that is co-location, not a
side effect, and it is why `app_layout()` registers the navbar toggle. Anything
optional waits for the app to ask. The function stays public and idempotent
either way, for the app that mounts the same id in a layout of its own.

`@callback`, not `@app.callback`: Dash's module-level `callback` registers into
the same global registry, so the function needs no `app` argument and the
framework never has to be handed the app object. Registration functions are
**idempotent** — an app may reach one from more than one place, and a second
`@callback` on the same output is a `DuplicateCallback`.

```python
# In layouts.py
_navbar_callbacks_registered = False


def register_navbar_callbacks():
    """Register the navbar-collapse toggle (idempotent)."""
    global _navbar_callbacks_registered
    if _navbar_callbacks_registered:
        return
    _navbar_callbacks_registered = True

    @callback(
        Output(NAVBAR_COLLAPSE_DIV_SHARED_ID, "is_open"),
        Input(NAVBAR_TOGGLER_BUTTON_SHARED_ID, "n_clicks"),
        State(NAVBAR_COLLAPSE_DIV_SHARED_ID, "is_open"),
        prevent_initial_call=True,
    )
    def toggle_navbar_collapse(n_clicks, is_open):
        ...

# In layouts.py, from the function that mounts the navbar
def app_layout(...):
    register_navbar_callbacks()
    ...

# In app.py, only for an app building its own navbar around the shared id
register_navbar_callbacks()
```

The framework ships one of these, `register_navbar_callbacks()`, called by
`app_layout()`. The example's job reset follows the same shape in its own
package: `csv_profiler.job_reset.job_reset_components()` returns the modal and
store and registers their callbacks (until v0.13.0 this was
`app_layout(with_reset=True)` in the framework).

---

## Common Patterns

### `prevent_initial_call=True`
For user-triggered actions only:
```python
@callback(..., prevent_initial_call=True)
def handle_click(n_clicks):
    ...
```

### `allow_duplicate=True`
When multiple callbacks output to same component:
```python
@callback(
    Output(STORE_ID, "data", allow_duplicate=True),
    ...
    prevent_initial_call=True,
)
```

### Loading Overlay — Clientside Only

The shared loading overlay (`LOADING_OVERLAY_SHARED_ID`) uses a two-callback pattern:
a fast callback opens it (`is_open=True`), a slow processing callback closes it
(`is_open=False`). The opening callback **must** be a `dash.clientside_callback`.

**Why:** With `allow_duplicate=True`, Dash does not guarantee execution order of
server-side callbacks targeting the same output. A server-side `show_loading` can fire
*after* the processing callback returns, leaving the overlay permanently stuck open.
Clientside callbacks execute instantly in the browser, guaranteeing the overlay opens
before the server roundtrip begins.

**No shared inputs:** Dash generates `allow_duplicate` callback IDs by hashing the
**inputs** (SHA-256 of all `Input()` specs joined together). If the clientside (open)
callback and the server-side (close) callback share the exact same inputs, Dash produces
identical callback IDs and raises an "already in use" error. The clientside callback must
use a **different set** of inputs — typically only the button click(s), while the
server-side callback includes an additional dummy/store input for differentiation.

**Debugging hash collisions:** The error message includes a hash suffix like
`output-id.prop@<hex>`. To identify *which* callback collides, compute the SHA-256 of
the dot-joined `Input()` specs (e.g.
`hashlib.sha256("btn-id.n_clicks.store-id.data".encode()).hexdigest()`) and match it
against the hash in the error. This pinpoints the exact pair of callbacks sharing inputs.

```python
# CORRECT — clientside, fires instantly in the browser
import dash

dash.clientside_callback(
    "function(n) { return true; }",
    Output(LOADING_OVERLAY_SHARED_ID, "is_open", allow_duplicate=True),
    Input(SOME_BUTTON_ID, "n_clicks"),
    prevent_initial_call=True,
)

# The processing callback closes it when done
@callback(
    Output(LOADING_OVERLAY_SHARED_ID, "is_open", allow_duplicate=True),
    ...
    Input(SOME_BUTTON_ID, "n_clicks"),
    prevent_initial_call=True,
)
def process(n_clicks, ...):
    # ... slow work ...
    return False  # closes overlay
```

```python
# WRONG — server-side show_loading races with the processing callback
@callback(
    Output(LOADING_OVERLAY_SHARED_ID, "is_open", allow_duplicate=True),
    Input(SOME_BUTTON_ID, "n_clicks"),
    prevent_initial_call=True,
)
def show_loading(n_clicks):
    return True
```

**Multiple triggers:** For callbacks with several button inputs, check any non-null:

```python
dash.clientside_callback(
    """
    function() {
        for (var i = 0; i < arguments.length; i++) {
            if (arguments[i] != null) return true;
        }
        return false;
    }
    """,
    Output(LOADING_OVERLAY_SHARED_ID, "is_open", allow_duplicate=True),
    Input(BUTTON_A_ID, "n_clicks"),
    Input(BUTTON_B_ID, "n_clicks"),
    prevent_initial_call=True,
)
```

**Testing note:** With clientside overlay callbacks, Dash callback chains may cascade
(e.g. a submit callback re-fires after a refresh, triggering a second refresh cycle).
Use overlay wait timeouts of at least 20s in Playwright tests to accommodate this.

### Dict-Style Callbacks for Many Outputs

When a callback has **5+ outputs**, use dict-style `output={}`, `inputs={}`, `state={}`
instead of positional arguments. This makes return values self-documenting and eliminates
the error-prone counting of tuple positions.

**Keys must be valid Python identifiers** (underscores, not hyphens). The HTML ID string
values are unaffected — only the dict keys need to be identifiers.

```python
@callback(
    output={
        "log_content": Output(LOG_OUTPUT_DIV_LOGS_ID, "children"),
        "pid_disabled": Output(LOG_PID_INPUT_LOGS_ID, "disabled"),
        "interval_disabled": Output(AUTO_POLL_INTERVAL_LOGS_ID, "disabled"),
    },
    inputs={
        "n_clicks": Input(REFRESH_BUTTON_LOGS_ID, "n_clicks"),
    },
    state={
        "date": State(LOG_DATE_PICKER_LOGS_ID, "date"),
    },
    prevent_initial_call=True,
)
def log_manager(n_clicks, date):
    return {
        "log_content": "...",
        "pid_disabled": False,
        "interval_disabled": True,
    }
```

For branches that only update a subset of outputs, use a `no_update` baseline helper:

```python
def _no_update_result():
    return {
        "interval_disabled": no_update,
        "end_hour_value": no_update,
        # ... all control outputs default to no_update
    }

# In callback branch:
result = _no_update_result()
result.update({"log_content": content, "pid_disabled": disabled_pid})
return result
```

### `PreventUpdate`
Stop callback execution for guard conditions:
```python
from dash.exceptions import PreventUpdate

@callback(...)
def process(n_clicks, data):
    if n_clicks is None:
        raise PreventUpdate
    if not data:
        raise PreventUpdate
    # proceed
```

### Identifying the Trigger

**Never use `ctx.triggered_id` or `triggered[0]`** — Dash can batch multiple input
changes into a single callback invocation (e.g., a field change and a button click
arriving together). `triggered[0]` picks whichever input appears first in the callback
definition, silently ignoring the rest. `ctx.triggered_id` is syntactic sugar for the
same thing.

Build a set filtered by `value is not None` to handle both batching and
`prevent_initial_call="initial_duplicate"` (where all inputs appear in `triggered`
with null values on page load):

```python
from dash import callback_context

triggered_ids = {
    t["prop_id"].split(".")[0]
    for t in callback_context.triggered
    if t["value"] is not None
}

if BUTTON_1_ID in triggered_ids:
    # handle button 1
elif BUTTON_2_ID in triggered_ids:
    # handle button 2
```

**Why `is not None`:** In multi-page apps, navigating to a page re-renders its
components. Dash fires callbacks with ALL inputs in `triggered`, but buttons that
were never clicked have `n_clicks: null`. Without the filter, the set would contain
every button on every page load.

**When `triggered[0]` is acceptable:** Only in callbacks with a single `Input()` where
batching is impossible. If there are two or more `Input()` entries, use the set.

---

## File Structure

Standard organization in page files:

```python
# 1. Module docstring
"""Page description."""

# 2. Imports
from dash import html, callback, Input, Output
from src.constants.html_ids import ...
from src.layout import ...

# 3. Page registration
register_page(__name__, path="/page", name="Page", title="Page Title")

# 4. Layout function
def layout(job_id=None):
    ...
    return page_container_split_layout(map, input_container)

# 5. Helper functions (if needed)
def validate_input(value):
    ...

# 6. Callbacks section
@callback(...)
def callback_1(...):
    ...

@callback(...)
def callback_2(...):
    ...
```
