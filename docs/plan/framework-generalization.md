# Plan: COSMO Framework Generalization — Layer A (Branding) + Layer B (Plugin Seam)

**Created:** 2026-06-29 · **Status:** design locked, implementation not started · **Scope:** cross-repo (cosmo-template, cosmopolitan, cosmonaut)

**Context:** For a SoftwareX paper we want to present one *general* Python-only Dash framework with three instantiations (CSV-profiler template, CRNS soil-moisture, survey routing) instead of three CRNS-labelled forks. This is the verified A+B design, produced by a map → design → adversarial-critique → reconcile workflow. Source maps and critiques live in the session that generated it.

---

## COSMO Framework — Final Design: Layer A (Branding) & Layer B (Plugin Seam)

> Verified against the real trees on 2026-06-29. Where a draft claim collided with a critique, I checked the source and state the verdict inline. Key corrections folded in: **there is no Alembic — schema is `docker/init.sql`**; **the map is a plugin-level app-shell, not an `InteractiveInputStage` sub-feature**; **page-registry key is the short `pages.x` form**; **`load_plugin()` must be import-time-self-healing, not hand-ordered**; **two `cosmo_core` copies exist through Step 8, so effort is per-fork**; **the test harness and `docker/init.sql` are themselves extension points**.

---

## 0. Locked product decisions (2026-06-29)

Three product decisions were taken with the maintainer (Louis) on 2026-06-29 and are now fixed. They **override** any conflicting recommendation in the body below (notably the i18n call in §2.7 and the first-step in the closing section).

1. **Bilingual UI (EN primary, DE secondary) is in scope** — not English-only. But translation is **build-time, not runtime**: DeepL (or an LLM) drafts the German from the English source, a human curates the domain terminology, and the committed artifact is **static**. No translation service is called at runtime — that would break the Python-only / self-contained story and mistranslate domain terms ("neutron count", "predictor"). Mechanism: a **lightweight per-locale `terms` + `markdown` map on `BrandingProfile`** (see revised §2.3), `t(key, lang)`. Full gettext/Babel is **deferred** — more machinery than EN+DE warrants and it fights Dash's import-time `register_page`. Accepted caveat: the **browser-tab title stays in the default locale (EN)** because `register_page(title=)` runs at import time with no request/locale context; only in-page content is localized.
2. **Distribution = separate repos + a shared `cosmo-core` pip package** (not one repo with `COSMO_DOMAIN` selecting the domain at deploy time). This confirms the Layer C direction in §5; precedent is `dash_form_factory`, already a shared package all three import.
3. **The cosmo-template CSV-profiler counts as a third reference instantiation** in the paper. It therefore becomes the **canonical minimal domain** and — being domain-free — the **clean build-ground for `cosmo-core` and the plugin contract**. This refines the recommended first step (see closing section): stand up the core in the template first, then onboard template → cosmopolitan → cosmonaut.

---

## 1. Executive summary + the framework/domain mental model

### Mental model
The skeleton "upload input → run background job → show results" becomes a **single-domain-per-process plugin system**. The generic core (`cosmo_core`) owns the *workflow machinery*; a **domain** owns *what flows through it*. Exactly one domain is active per process, chosen by one env var `COSMO_DOMAIN`.

```
                 ┌─────────────────────── cosmo_core ───────────────────────┐
COSMO_DOMAIN ──▶ │ registry → DomainPlugin (Protocol)                        │
                 │   workflow: Dash pages, navbar/doc/screenshot composition │
                 │   Job lifecycle, Celery wiring, DB core tables,           │
                 │   error modal, object storage, logs                       │
                 └──────────────────────────┬────────────────────────────────┘
                                            │ contributes
        ┌───────────────────────────────────┼───────────────────────────────────┐
   cosmopolitan_domain (CRNS/RF/TimeIO)              cosmonaut_domain (routing/OSM)
   branding • computation • schema • forms           branding • computation • schema • forms
   connector(sync TimeIO) • tasks                    connector(async OSM) • tasks
   interactive_stages=[] • app_shell=None            interactive_stages=[Street] • app_shell=SplitMap
   workflow=None (flat navbar)                       workflow=[6 ordered steps]
```

**The framework/domain boundary, stated as a rule:** `cosmo_core` may know about *jobs, files, tasks, queues, pages, navbar, errors, storage, logs, and core DB tables*. It must know **nothing** about CRNS, soil moisture, TimeIO, streets, routes, OSM, GPX, EPSG, or any raster/vector output shape. CI enforces this with a grep gate (Section 4).

### What this design commits to (opinionated calls, all upheld under critique)
1. **Env-var dotted-module registry** over `entry_points`. One domain is ever active; auto-discovery is anti-value here. (Upheld by all three critiques.)
2. **`typing.Protocol`** contracts over ABC — structurally typed, tolerant of the forks' incidental drift, statically checkable.
3. **No shared `result.json` schema.** The two outputs (GeoTIFF raster vs GPX/QR + map polyline) are genuinely irreconcilable. Confirmed: `cosmonaut_job.py:get_route_polyline` feeds a shell-map callback, not a result component.
4. **Bilingual (EN+DE) per-locale `terms`/`markdown` map, not gettext** *(revised — see Decision 1 / §2.7)*. Translations are static and authored build-time (DeepL-drafted, human-curated); no runtime translation service. `BrandingProfile.t(key, lang)` is the access point; gettext/Babel deferred.
5. **The map is a first-class optional app-shell**, not buried in `InteractiveInputStage` — the single biggest correction from the critiques (see 3.4).
6. **Schema seam owns a DDL fragment of `docker/init.sql`, not Alembic** — Alembic does not exist (verified: only `./docker/init.sql`, no `create_all` anywhere).

---

## 2. LAYER A — Branding / terminology externalization

### 2.1 The central import-time fact (corrected)
`dash.register_page` runs at import time, `dash.page_registry` is read at import time, `Dash(title=)` is set at construction, **and** domain singletons are built at import time: `cosmopolitan_app/form_template_factory.py:413 active_form_factory = FormFactory(...)`, and `cosmonaut_app/layout.py:48-49` monkeypatches `_default_name_space.dump` before Dash harvests clientside callbacks. So "resolve the plugin before the first page import" is necessary but **not** sufficient — it must precede the first *transitive* `active_plugin()` read anywhere.

**Resolution (folds in feasibility blocker + completeness major):** make plugin resolution an **idempotent, self-healing module-import side effect**, not a hand-ordered entrypoint call.

```python
# cosmo_core/plugin_registry.py
import importlib, os
from cosmo_core.contract import DomainPlugin

_PLUGIN: DomainPlugin | None = None

def _load() -> DomainPlugin:
    # COSMO_DOMAIN is required; direct access (no .get) per convention — a missing
    # domain is a hard, loud boot error, which is correct.
    module = importlib.import_module(os.environ["COSMO_DOMAIN"])
    plugin = module.plugin
    assert isinstance(plugin, DomainPlugin), f"{os.environ['COSMO_DOMAIN']}.plugin does not satisfy DomainPlugin"
    return plugin

def active_plugin() -> DomainPlugin:
    """First access lazily resolves; subsequent accesses return the cached singleton.
    Self-healing ordering: any consumer that reads the plugin triggers the load."""
    global _PLUGIN
    if _PLUGIN is None:
        _PLUGIN = _load()
    return _PLUGIN
```

Ordering is then *enforced*, not *documented*: an **import-linter contract** forbids any `cosmo_core.pages.*` / `layouts` / `form_*` module-body access to `active_plugin()` from importing the registry before `COSMO_DOMAIN` can be set, and a **subprocess test imports each entrypoint with `COSMO_DOMAIN` unset** to prove the failure is loud (KeyError on env), not a partial init. Web entrypoint imports pages+layouts; the worker imports `job`/`tasks` and **no** pages — the contract is "registry hot before any consumer body," uniform across entrypoints because resolution is lazy.

### 2.2 The page-registry key (corrected — was a latent boot crash)
Verified: navbar reads the **short** form `dash.page_registry["pages.home"]` (`cosmopolitan_app/layouts.py:52+`), while pages call `register_page(__name__)` with the **full** path `cosmopolitan_app.pages.home`. The contract pins the **short key** as canonical.

```python
# cosmo_core/pages/_register.py
import dash
from cosmo_core.plugin_registry import active_plugin

def _short_key(module_name: str) -> str:
    # "<pkg>.pages.home" -> "pages.home" (the dash.page_registry key form)
    return "pages." + module_name.rsplit(".", 1)[-1]

def register(module_name: str, *, path=None, path_template=None):
    plugin = active_plugin()
    b = plugin.branding
    meta = plugin.page_meta(_short_key(module_name))   # keyed on short form
    dash.register_page(module_name, name=meta.name,
                       title=f"{b.app_name} - {meta.title}",
                       description=meta.description, path=path, path_template=path_template)
```
A **startup assertion** checks `set(plugin.pages()) == {k for k in dash.page_registry if k owned-by-plugin}` so any drift fails loudly with a clear message, never a bare `KeyError` under the no-defensive rule.

### 2.3 The profile schema
A frozen dataclass owned by the domain (not pydantic — never crosses a wire). **Scope correction:** `terms` covers *Python-rendered chrome strings only*. It explicitly does **not** reach backend pydantic `Field(description=...)` tooltips (owned by `computation.config_model`, surfaced by `forms`) nor JS tooltip property names (domain-package JS). Map center/zoom is **removed** from branding (see below).

```python
# cosmo_core/branding.py
from dataclasses import dataclass, field

@dataclass(frozen=True)
class PageMeta:
    name: str; title: str; description: str = ""
    nav: bool = True; nav_group: str = "workflow"   # "workflow" | "admin"
    doc_body: str = ""   # user-facing doc copy for core pages (replaces docstring-as-content)

@dataclass(frozen=True)
class BrandingProfile:
    app_name: str          # ONE source — collapses MAP-A's 5 drifting copies
    tagline: str
    logo_svg: str; logo_alt: str        # fixes cosmonaut's stale alt="Cosmopolitan Icon"
    favicon: str; home_banner: str
    default_lang: str = "en"             # tab-title locale + fallback (Decision 1)
    theme_css: str = "/assets/flatly_bootstrap.css"
    # REVISED per Decision 1: two-dimensional, lang -> key -> string. intro/workflow/admin/
    # footer markdown live inside each lang block of `markdown`.
    terms: dict[str, dict[str, str]] = field(default_factory=dict)
    markdown: dict[str, dict[str, str]] = field(default_factory=dict)
    # NOTE: NO version field — doc_version.txt stays per-fork (reads pyproject version).
    # NOTE: NO map center/zoom — that is geographic domain data, not app identity.

    def t(self, key: str, lang: str | None = None, **fmt) -> str:
        block = self.terms[lang or self.default_lang]      # fail-loud on unknown lang/key
        return block[key].format(**fmt) if fmt else block[key]
```

**Map center/zoom removed from `BrandingProfile` (minor critique, accepted).** Today the center `[51.70,11.20]` is already duplicated (`pydantic_models.py` default + `layout.py build_global_map`). Putting it in branding makes a third copy. It lives in the **domain package's constants** (or the `ShellComponent` config) as the single source; the pydantic default and `build_global_map` route through it. `OSM_TAGS_MAPPING` similarly stays in domain constants and is exposed to *both* `DomainForms` and the interactive stage — not labeled a forms-only concern.

### 2.4 The five app-name sinks → one source
| Sink | Today | After |
|---|---|---|
| `Dash(title=)` | absent (pol), inline (naut) | `Dash(title=branding.app_name)` in core `app.py` |
| navbar brand + logo `<img>` | inline literal + hardcoded src/alt | `branding.app_name`/`logo_svg`/`logo_alt` in core `create_navbar()` |
| `register_page(title=)` | 3/13 vs 11/11 inconsistent | `register()` chokepoint applies `f"{app_name} - {meta.title}"` uniformly |
| `doc_generator` INTRO/WORKFLOW/ADMIN | hardcoded strings | `branding.*_markdown` |
| generated `documentation.md` | committed artifact | regenerated; no literals to drift |

### 2.5 The docstring trap + committed-doc invariant (corrected check)
Generic-page docstrings are compiled into `documentation.md` by `doc_generator`. Fix: core-page docstrings become dev comments; their user copy moves into `PageMeta.doc_body`. Domain-package page docstrings remain content. **Correction (completeness major):** `test_documentation_version.py` gates `documentation.md` freshness against the per-fork pyproject version, and the docstring refactor **intentionally changes** generated output — so "diff to confirm parity" is the wrong check. The correct step is: *regenerate → review the semantic diff → re-commit `documentation.md` + bump `doc_version.txt`*. `doc_version.txt` stays per-fork; `BrandingProfile` must not own a version.

**Convention to record** (`docs/conventions/`): *a docstring is doc content only for domain-package pages; core-package page docstrings are dev comments and their doc copy comes from `PageMeta.doc_body`.*

### 2.6 Terms population without boot crashes (minor critique, accepted)
`terms` is fail-loud and read at import (titles). Therefore terms are **append-with-consumer**: a key is added in the same change that introduces its `t()` call site — never referenced before it exists. A CI self-check greps `t("KEY")` literals and asserts each key is present, so a missing key fails the suite, not a user page.

### 2.7 i18n decision (REVISED per Decision 1 — bilingual EN+DE)
Bilingual EN (primary) + DE (secondary) via a **lightweight per-locale `terms`/`markdown` map**, not gettext/Babel. Translations are **static, authored build-time**: DeepL (or an LLM) drafts the German from the English source, a human curates domain terms, the committed strings are fixed — **no runtime translation service** (preserves Python-only/self-contained; avoids mistranslating "neutron count"/"predictor"). gettext/Babel is **deferred**, not adopted: more machinery than EN+DE warrants and its locale selection fights import-time `register_page`. Locale selection is a simple mechanism (URL prefix or user setting). **Caveat:** the browser-tab title (`register_page(title=)`) stays in `default_lang` (EN) — import time has no request/locale context; only in-page content is localized. `t(key, lang)` is the single access point and the upgrade seam to gettext if translator tooling is ever needed.

---

## 3. LAYER B — The framework/domain plugin contract

### 3.1 The aggregate contract (revised for both domains)
```python
# cosmo_core/contract.py
from typing import Protocol, runtime_checkable
from pydantic import BaseModel
from cosmo_core.branding import BrandingProfile, PageMeta

@runtime_checkable
class DomainSchema(Protocol):
    """Owns ORM classes + the DDL fragment. SINGLE source of ORM registration."""
    def orm_tables(self) -> list[type]: ...     # extra DeclarativeBase subclasses, ONE shared MetaData
    def job_columns(self) -> list: ...          # extra JobTable columns INCLUDING sub-job tracking (e.g. membership_upload JSON, stage int)
    def ddl_fragment(self) -> str: ...          # domain_init.sql: tables + indexes + seed INSERTs (NOT Alembic)

@runtime_checkable
class DomainComputation(Protocol):
    config_model: type[BaseModel]               # extends/re-exports backend config (ModelWebsite / UserModel)
    def ingest_input(self, job, file_path: str, kind: str, params: dict) -> None: ...
        # may read sibling files in job.working_dir, raise FileValidationError, and perform
        # side effects (coord transform, derive bounds, dispatch acquisition TaskSpec)
    def prepare_work_dir(self, job) -> None: ...
    def run(self, work_dir: str) -> None: ...                # smp_cli.main / sensor_routing_pipeline
    def result_artifacts(self, job) -> None: ...             # worker-side: GeoTIFF tiles | GPX+QR
    def result_view(self, job): ...                          # in-page Dash component OR None (naut returns None)

@runtime_checkable
class DataConnector(Protocol):
    """Sync (TimeIO pull) OR async (OSM background job). References tables by name only
    — does NOT re-declare/return ORM classes (single-source via DomainSchema)."""
    def admin_pages(self) -> list[str]: ...
    def acquisition_tasks(self) -> list["TaskSpec"]: ...      # beat-scheduled update | upload task
    def status_column(self) -> str | None: ...               # domain job column holding sub-job status, or None

@runtime_checkable
class DomainForms(Protocol):
    def form_cards(self) -> list: ...                        # FormTemplateFactory card specs
    def preprocess_form_data(self, raw: dict) -> dict: ...
    # field coverage of config_model is asserted at startup (3.6)

@runtime_checkable
class ShellComponent(Protocol):
    """NEW first-class optional app-shell (the split-view map). None for cosmopolitan."""
    wraps_page_container: bool                               # True => two-column split, False => single column
    def build_shell_slot(self): ...                          # the persistent left-column map
    def register_shell_callbacks(self, app) -> None: ...     # viewport streaming, recentre-on-job, polyline-by-pathname

@runtime_checkable
class InteractiveInputStage(Protocol):
    """Optional editing stage. Contributes layers/edit-callbacks to the ShellComponent;
    does NOT own the shell. [] for cosmopolitan."""
    edit_state_model: type[BaseModel]                        # street_edits.json
    def derive(self, job) -> None: ...
    def shell_layers(self, job) -> list: ...                 # layers it adds to the shell map
    def register_callbacks(self, app) -> None: ...
    def page_module(self) -> str: ...
    js_module: str | None                                    # import-time JS/Namespace side-effect module (3.7)

@runtime_checkable
class WorkflowStep(Protocol):
    page_module: str; label: str
    def gate(self, job) -> bool: ...                         # step-completion predicate

@runtime_checkable
class DomainTasks(Protocol):
    def task_specs(self) -> list["TaskSpec"]: ...
    def submit_methods(self) -> dict[str, callable]: ...     # name -> submit_*; mounted on BackgroundJobManager

@runtime_checkable
class DomainConfig(Protocol):
    """Domain-only env keys + external endpoints (TimeIO base_url, Overpass, TILESERVER_URL)."""
    def env_keys(self) -> dict[str, object]: ...

@runtime_checkable
class DomainTestFixtures(Protocol):
    """Makes the test harness an extension point (completeness blocker)."""
    celery_dotted_path: str
    def test_queues(self) -> list[str]: ...
    def sample_inputs(self) -> dict: ...                     # crns/pred analogue
    def e2e_artifacts(self) -> list[str]: ...

@runtime_checkable
class DomainPlugin(Protocol):
    branding: BrandingProfile
    computation: DomainComputation
    schema: DomainSchema
    forms: DomainForms
    connector: DataConnector | None
    interactive_stages: list[InteractiveInputStage]          # [] for cosmopolitan
    app_shell: ShellComponent | None                         # None for cosmopolitan
    workflow: list[WorkflowStep] | None                      # None => flat navbar
    tasks: DomainTasks
    config: DomainConfig
    test_fixtures: DomainTestFixtures
    def pages(self) -> list[str]: ...                        # short keys; drives navbar + docs (NOT discovery)
    def page_meta(self, short_key: str) -> PageMeta: ...
    def register_callbacks(self, app) -> None: ...           # ordered phase, see 3.8
```
`TaskSpec` is a frozen dataclass `(fn, name, queue, base_task, beat=None)` feeding both `celery_app.py` registration and `celery_config` `task_routes`/`beat_schedule`.

> **Shipped with roadmap step #4 (one Celery app, v0.14.0):** `cosmo_ecosystem.task_spec.TaskSpec` in exactly this shape (`beat` is a `BeatEntry`: schedule plus optional options), and `COSMO_DOMAIN` as the discovery variable, naming a domain module with plain attributes (`task_specs`, `celery_config`, `excluded_log_packages`, `log_retention_days`) rather than a `plugin` object. `cosmo_ecosystem.celery_app` derives routes, `task_queues` and the beat schedule from the specs. See ADR 0003.

### 3.2 Registration mechanisms
- **Domain → core:** lazy self-healing registry (3.1/2.1).
- **Pages → Dash:** keep `Dash(use_pages=True)` auto-discovery. `plugin.pages()` drives **navbar + doc + screenshot composition only**, replacing hardcoded nav lists and `screenshot_generator.PAGES_TO_CAPTURE`.
- **Tasks → Celery:** `celery_app.py` iterates `tasks.task_specs() + connector.acquisition_tasks()`; `celery_config` builds routes/beat from the same specs; `submit_methods()` mounts on `BackgroundJobManager`.
  > **Superseded for submissions (ADR 0003):** nothing is mounted on the manager. Domain submissions are module functions in the app that call the framework manager's `submit_job` / `submit_named_job` (the csv_profiler pattern); mounting is a registration side effect the framework does not need.
- **ORM → metadata:** **only** `schema.orm_tables()` registers classes (single MetaData shared with core), collected exactly once — closes the double-registration risk (minor critique). `DataConnector` references tables by name, never re-declares.

### 3.3 Killing every coreLeak — unchanged from draft except: `job.py` extraction is **complete** (feasibility major). Step 4 must relocate **all** of: `draw_preview`, `preview_area`, `_write_crns`, `safe_input_file`, the `crn_`/`pred_` prefix conventions, **and the top-level `from ...timeio_info import type_id_dict` import**. `draw_preview` (PostGIS + staticmaps render) is presentation+domain and moves to a domain page helper / `result_artifacts`-adjacent code, not core `Job`. CI grep gate: core `job.py` has zero `soil_moisture_prediction`/`timeio` imports — until clean, "core owns Job" is false and the worker still drags domain code.

### 3.4 The shell map — promoted to first-class (BLOCKER fix, verified)
Verified: `cosmonaut_app/layout.py:374-377` wraps **every** page as `[build_global_map() col-7, page_container col-5]`. The map is written by `data_upload.py` (membership tile + viewport), `route_computation.py` (polyline via `layout.py:update_map_layers` keyed on pathname), and `street_selection.py` (the true stage). So the map is a **cross-cutting shell**, not an `InteractiveInputStage` sub-feature.

**Resolution:** `DomainPlugin.app_shell: ShellComponent | None` owns the shell — `build_shell_slot()`, `register_shell_callbacks(app)`, and `wraps_page_container` which switches `app_layout()` between cosmopolitan's single column and cosmonaut's two-column split. Upload and compute pages target the shell directly. `InteractiveInputStage` only *contributes* `shell_layers(job)` + edit callbacks. **Cosmopolitan: `app_shell=None`, `interactive_stages=[]` → single-column, zero shell code paths exercised.**

**Honest cost (minor critique, accepted):** the shell machinery and its `dash_extensions`/`dash-leaflet` weight live in `cosmo_core` to be available to cosmonaut, so cosmopolitan's package inherits the *code surface* even at `None`. **Decision: keep the `ShellComponent` Protocol in core but keep the implementation in the cosmonaut domain package until a second domain needs a map.** Core declares the seam; the exemplar stays domain-side. This honors the "not speculative" principle and avoids over-fitting generic code to one consumer.

### 3.5 Output seam split (major fix, verified)
`result_view(job) -> component` was the wrong shape for cosmonaut: verified, there is no results page returning a component — the route polyline is injected into the shell map by `update_map_layers` via `cosmonaut_job.get_route_polyline`, and GPX/QR are worker-built (`create_qr_code_routing`). So the seam is split:
- `result_artifacts(job)` — worker-side: GeoTIFF tiles (pol) | GPX+QR (naut).
- `result_view(job) -> component | None` — in-page render; **naut returns `None`** and instead contributes a shell layer via the `ShellComponent`/stage.

### 3.6 Ingest seam enriched (major fix, verified)
`validate_input(path, kind) -> None` could not express cosmonaut's reality: `upload_membership` (`cosmonaut_job.py:333`) validates **and** transforms coordinates (needs EPSG from the *same* upload action), computes bounds/center/zoom, **and** dispatches the OSM task; `upload_predictor` cross-validates against the already-on-disk membership file (`validate_predictor_membership_consistency:412`). New signature: `ingest_input(job, file_path, kind, params: dict) -> None` — has the job (sibling files via `job.working_dir`), the scalars (`params["epsg"]`), may raise `FileValidationError`, may have side effects. Cosmopolitan's crn/pred parsers fit trivially. A side-effect-free `validate_input` is kept only if ever needed.

Plus the **field-partition assertion** cosmonaut depends on (minor critique): at `load_plugin()`, assert `union(fields referenced by forms.form_cards()) ⊇ computation.config_model.model_fields − declared hidden/exclude`. Preserves cosmonaut's import-time guarantee (add a backend field → form must surface it) inside the framework, failing loud.

### 3.7 Sub-job state + async acquisition (major fix, verified)
Verified: cosmonaut stores the OSM-download sub-job lifecycle **inside the domain `membership_upload` JSON column** — `get_street_processing_status` (`cosmonaut_job.py:440`) reads a Celery task id or `PENDING/COMPLETED/FAILED`; `stage` int gates the wizard. So the core must **not** assume one async job per row. Resolution: `DomainSchema.job_columns()` explicitly owns sub-job tracking columns; `DataConnector.status_column()` declares which domain column tracks acquisition status (vs the generic `celery_task_id`). The core registers `acquisition_tasks()` specs and offers a generic poll that reads `status_column()`. Cosmopolitan: synchronous TimeIO, `status_column()=None`, tracks none.

### 3.8 Callback-registration lifecycle (major fix, verified)
Verified two distinct styles: cosmopolitan registers `@callback` at import; cosmonaut calls `register_navbar_callbacks(app)`, `register_reset_callbacks(app)`, `register_map_callbacks(app)` after `app.layout = app_layout()` (`cosmonaut_app/app.py:45-47`). Core `app.py` standardizes one **ordered phase**:
```
1. (import) registry resolves lazily on first active_plugin() read
2. Dash(use_pages=True, title=branding.app_name, assets_folder=<domain>, assets_url_path=...)
3. app.layout = app_layout()                 # single-col, or split if plugin.app_shell
4. plugin.register_callbacks(app)            # no-op for cosmopolitan (import-time)
5. plugin.app_shell.register_shell_callbacks(app)        # if app_shell
6. for s in plugin.interactive_stages: s.register_callbacks(app)
```
Pure-core generic-page callbacks stay import-time. Any plugin-contributed callback needing an `app` handle uses `register_*(app)`.

### 3.9 The `assign()` / Namespace monkeypatch + JS assets (major fixes, verified)
Verified: `cosmonaut_app/layout.py:48-49` does `_default_name_space.dump = lambda ...` at **import** to redirect generated clientside JS into the package assets dir, before Dash harvests callbacks. This is global, import-time, order-sensitive against `dash_extensions` internals and cannot be deferred to a getter. Resolution:
- `InteractiveInputStage.js_module: str | None` names the module whose **import** performs the `assign()`/Namespace side effect. The registry imports `js_module` via `importlib` **before** Dash construction.
- Per-domain JS (`filter_features.js`, `dashExtensions_default.js`, `geojson_functions.js`) ships in the **domain package's `assets/`**, never `cosmo_core`. Dash `assets_folder`/`assets_url_path` is set from the plugin (cosmonaut already sets `assets_url_path`). The `assign()` Namespace target dir is the domain's assets dir.
- Documented as a **known fragile coupling** to `dash_extensions` internals owned by the stage; flagged as the highest-risk item in Step 8.

### 3.10 DB schema seam — DDL fragment, NOT Alembic (BLOCKER fix, verified)
Verified: no `alembic.ini`, no `env.py`, no migrations dir, no `create_all` anywhere; the only schema source is `./docker/init.sql` (monolithic, interleaves generic + domain tables, has `DROP TABLE IF EXISTS`, embeds the prod runbook as comments). **`alembic_revisions_path()` is deleted — it has no referent.** Replacement:
- Core ships `core_init.sql` (`jobs`, `logs`, `task_lock`, `update_db_runs`, `app_config`).
- `DomainSchema.ddl_fragment()` returns `domain_init.sql` (its tables, indexes, seed `INSERT`s like `crns_start_date`). Concatenated at container init / test setup.
- **Stated honestly:** `JobTable` is declared **twice today** — Python ORM (`postgres_manager.py`/`db_manager.py`) **and** raw DDL in `init.sql` — kept in sync by hand. `job_columns()` drives the Python side; the matching DDL is in `ddl_fragment()`. Picking a single source of truth (e.g. moving to `create_all`) is an **explicit prerequisite project**, not a line item inside Step 5.
- **Open decision flagged:** `app_config` seed rows `crns_start_date`/`crns_end_date` are domain data in a "generic" table — decide whether `app_config` is core or domain-extensible (Section 6).
- Net resizing: moving ORM classes is a **pure Python-import reorg with zero DDL/data effect** → Step 5 is **M, not M/L**.

### 3.11 How BOTH domains map
**Cosmopolitan (RF over TimeIO):** `branding` COSMOPOLITAN/`icon_white.svg`; `app_shell=None`; `interactive_stages=[]`; `workflow=None` (flat navbar); `connector` = sync TimeIO, `acquisition_tasks()` = one beat-scheduled `update-db`, `status_column()=None`, `admin_pages()=["crns_db_admin","sensor_management"]`; `schema` owns `crns_measurements`/`timeio_info`/`update_times_crns`; `computation.config_model=ModelWebsite`, `ingest_input` dispatches crn→SoilMoistureParser / pred→PredictorParser, `run=smp_cli.main`, `result_artifacts`=GeoTIFF tiles, `result_view`=tile maps + correlation/feature-importance; `config.env_keys` = TILESERVER_URL/EMAIL_*/MAINTAINER_EMAIL; `tasks`=`submit_computation_job`.

**Cosmonaut (routing over OSM):** `branding` COSMONAUT/`sample_logo.svg`/correct alt; `app_shell=SplitMap` (`wraps_page_container=True`, owns membership tile + route polyline + viewport streaming); `interactive_stages=[StreetSelectionStage]` (contributes street layers + `js_module`); `workflow=[6 ordered steps]` with `gate` predicates reading `stage`/`get_completed_steps`; `connector` = async OSM/Overpass, `acquisition_tasks()`=`process_upload_task` on `upload` queue, `status_column()="membership_upload"` (JSON `street_processing`); `schema` `job_columns()` includes `membership_upload`/`predictor_upload`/`epsg`/`config`/`stage`; `computation.config_model=UserModel(FullPipelineConfig)`, `ingest_input` membership(+EPSG transform, bounds, OSM dispatch)/predictor(cross-validate), `run=sensor_routing_pipeline`, `result_artifacts`=GPX+QR, `result_view=None` (route shown as shell layer); `config.env_keys` = Overpass endpoint; `tasks`=`submit_routing_job`, `submit_upload_job(job, epsg)` on `routing`/`upload` queues.

The **harder domain is cosmonaut** — `TaskSpec`, the ingest/shell/workflow seams must be validated against it **first**, not cosmopolitan.

---

## 4. In-place migration path + effort sizing

**Two `cosmo_core` copies exist, one per fork, through Step 8** (feasibility major, accepted). Every step is implemented **per fork**, so the sizes below are **per-fork**; total ≈ 1.7–2× a single-core reading, plus a reconciliation tax where cosmonaut's wiring differs. "Keeps both green" requires running **two** test suites with different wiring after each step. The test harness is generalized via `DomainTestFixtures` (3.1) so `conftest.py` parametrizes off `active_plugin()` instead of the literals verified today (`test/conftest.py:354 "cosmopolitan_app.celery_app.celery"`, `:359 "--queues=computation,maintenance,celery"`, `PostgresManager` import); `test_html_id_enforcement` reads the package path from env/plugin. Each step's "keeps-working" note names which test files it touches.

| Step | What | Keeps-working | Effort (per fork) |
|---|---|---|---|
| 1 | **App-name collapse only.** `BrandingProfile` + lazy registry; route the 5 app-name sinks. | Literal refactor; removes worst drift (pol missing `Dash(title=)`, naut stale alt). | **S** |
| 2 | **Full Layer A.** terms map, doc templates, asset indirection, core-docstring→`doc_body`. | doc_generator reads branding; **regenerate `documentation.md` + bump `doc_version.txt`** (not diff-parity); touches `test_documentation_version.py`. | **M** |
| 3a | **Protocols + branding-only plugin.** Wire only the app-name sinks through `plugin.branding`. | Genuine pass-through; nothing else moves. | **S** |
| 3b | **Route import-time singletons** through plugin: navbar from `plugin.pages()`, `register()` chokepoint, `active_form_factory` behind `forms`. Add import-linter contract + subprocess unset-env test. | Where import-order breakage surfaces; run **both** Playwright suites after. | **M** |
| 4 | **Extract `DomainComputation` fully out of `job.py`/tasks** — `draw_preview`,`preview_area`,`_write_crns`,`safe_input_file`, prefix conventions, `type_id_dict` import. Add `ingest_input`. | Highest-value leak fix; per-fork; CI grep gate: core `job.py` has zero domain imports. End-to-end job runs, not just unit. | **L** |
| 5 | **Split `DomainSchema`** — core keeps jobs/logs/task_lock/update_db_runs/app_config; domain ORM behind `orm_tables()`; split `init.sql` into `core_init.sql` + `ddl_fragment()`. | **Python-import reorg only; DB unchanged on disk; no Alembic, no data migration.** | **M** |
| 6 | **Task/connector seam.** `TaskSpec` drives celery_app/config (*`TaskSpec` shipped with roadmap step #4; `submit_methods()` dropped, see §3.2*); ~~`submit_methods()` on BJM~~; async acquisition + `status_column()`. **Validate against cosmonaut first** (two submit paths + second pre-compute job). | Task names/queues identical; only wiring source changes; touches conftest queues. | **M** |
| 7 | **Navbar/doc/screenshot composition** from `plugin.pages()` + `PageMeta`; add `workflow` stepper for naut. Remove hardcoded nav + `PAGES_TO_CAPTURE`. | Discovery stays Dash-native; only chrome changes. | **S/M** |
| 8 | **`ShellComponent` + `InteractiveInputStage` for cosmonaut.** Lift split-map shell + StreetSelector behind the Protocols; `js_module` imported pre-Dash. cosmopolitan stays `None`/`[]`. | cosmopolitan untouched; map ownership moves from `layout.py` to shell/stage. **Flag `dash_extensions._default_name_space.dump` monkeypatch as specific fragility.** | **L** |

After Step 8: each fork = `cosmo_core` (identical-by-intent) + domain package. **Env-var reconciliation** for cosmonaut (`POSTGRES_DB→POSTGRES_NAME`, `FLASK_DEBUG→DEBUG`) is its **own numbered step before Layer C-C**, surfaced via `DomainConfig` (completeness major) — not a one-line afterthought.

---

## 5. Layer C feasibility verdict

*(Decision 2 confirms this is the target: separate repos + a shared `cosmo-core` pip package — not one repo with `COSMO_DOMAIN` at deploy.)*

**Feasible, sequenced after Layer B, curated subset — not a wholesale `src/` lift.**
- **Extractable as `cosmo_core` with cosmopolitan as the SOLE first consumer:** `object_storage_manager.py`, `logs_table.py`, the `handle_error`/`error_modal`/`_truncate_*` core (byte-identical for pol), plus `files_route`/`logger`/`celery_app`/`config`/`app` within ~5–15 lines. **Correction (minor):** these same files are **SUBSTANTIAL in cosmonaut** (drops `get_presigned_download_url`, adds `ObjectStorageError`, changes `get_files` signature; `logs_table` drops `create_logs_container`, changes `color_map[level]`). So design the package API to **cosmopolitan's shape first** and absorb cosmonaut's drift as later reconciliation — otherwise `cosmo_core` ossifies and cosmonaut can never join without breaking changes. Strongest precedent: `dash_form_factory` is already a shared pip package all three import — the team has shipped shared framework code.
- **Hard prerequisite:** Job↔compute↔results couple through bare `result.json` dict keys with no shared type — **`cosmo_core` cannot own `Job`/results until Layer B formalizes the seam.** Layer B is prerequisite, not parallel.
- **Blocked until reconciled:** cosmonaut's renamed env vars, `register_*_callbacks(app)` lifecycle, `get_logger_config_web()` signature, `CosmonautJob` keyword-only ctor, divergent object-storage API, different exception taxonomy, 2.4×-template `layout.py`.
- **No end-user auth exists in either app** (only service secrets) — omitting an auth layer is correct, stated explicitly so no reviewer must re-verify.

**Sequence:** (C-A) externalize the already-identical infra into `cosmo_core`, cosmopolitan first consumer; (C-B) complete Layer B to formalize Job/compute/result; (C-C) reconcile cosmonaut's env/wiring/storage-API drift, then pull it onto the same `cosmo_core`. A single package owning Job/layout/results across both forks *today* is unrealistic.

---

## 6. Open decisions for maintainers
1. **`app_config` ownership.** It is a "generic" table holding domain seed rows (`crns_start_date`/`crns_end_date`). Core-owned table with domain-extensible seed, or domain-owned? Affects `core_init.sql` vs `ddl_fragment()` split.
2. **`JobTable` single source of truth.** It is declared twice (Python ORM + `init.sql`) and hand-synced. Adopt `create_all` to make Python authoritative (a prerequisite project), or keep `init.sql` authoritative and have `job_columns()` emit DDL? Recommend the latter short-term, former long-term.
3. **`ShellComponent` home.** Keep the map implementation in the cosmonaut domain package (recommended, avoids over-fitting) vs lift it into `cosmo_core` now. The Protocol lives in core either way.
4. **When to collapse the two `cosmo_core` copies** into one shared package — at end of Step 8, or only after cosmonaut env/API reconciliation (Layer C-C)?
5. **`WorkflowStep` reuse for cosmopolitan.** Cosmopolitan is flat today (`workflow=None`); is an ordered wizard ever wanted there, or is the stepper permanently cosmonaut-only?
6. **`COSMO_DOMAIN` value form** — bare module name (`cosmopolitan_domain`) vs dotted attribute path. Recommend bare module exposing `plugin`, set in k8s `values.yaml`.

---

## Recommended first step (REVISED per Decision 3 — build in the template)
**Stand up `cosmo-core` + the plugin contract in cosmo-template first**, with the CSV-profiler as the reference domain — *not* in cosmopolitan. The template is domain-free, so the registry, the locale-aware `BrandingProfile`, lazy self-healing resolution, and the **import-time ordering invariant + its import-linter/subprocess-unset-env guard** get built where there are **zero domain leaks to fight**. This also directly produces the paper's third instantiation. The contract is already cosmonaut-aware (the maps stress-tested it), so onboard in difficulty order afterwards: **template (trivial) → cosmopolitan (medium, "template + superset") → cosmonaut (hard: ShellComponent, sub-job status, JS monkeypatch as the L steps)**. Validate each onboarding against its Playwright suite.

*(The original recommendation — "Step 1 app-name collapse in cosmopolitan first" — remains a valid alternative if you'd rather start inside a live app; the template-first path is cleaner given Decision 3.)*

### Relevant verified paths
- `./docker/init.sql` (sole schema source; no Alembic)
- `cosmopolitan_app/layouts.py:52+` (short `pages.x` registry keys)
- `cosmopolitan_app/form_template_factory.py:413` (`active_form_factory` import-time singleton)
- `cosmonaut_app/app.py:45-47` (`register_*_callbacks(app)` lifecycle)
- `cosmonaut_app/layout.py:48-49` (`_default_name_space.dump` monkeypatch), `:308 build_global_map`, `:374-377` (split-view col-7/col-5)
- `cosmonaut_app/cosmonaut_job.py:382,440-468` (`street_processing` sub-job in `membership_upload` JSON), `:333,412` (ingest side effects + cross-file validation), `:525 get_route_polyline`
- `test/conftest.py:354,359` (hardcoded celery path + queues), `test/test_documentation_version.py`, `cosmopolitan_app/assets/docs/doc_version.txt`