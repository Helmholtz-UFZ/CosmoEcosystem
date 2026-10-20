# Skill: Run and Fix Failing Tests

Step-by-step checklist for running tests, diagnosing failures, and fixing issues in the Cosmo Ecosystem test suite.

---

## 1. Clarification Questions

Ask the user before starting:

1. **Failure location** — Did the test fail locally, in the CI pipeline, or both?
2. **Test scope** — Which test file is failing, or is it the full suite?
3. **New or regression** — Did this test pass before, or is it newly written?
4. **Error message** — What error are you seeing? (paste the output)

---

## 2. Step-by-step Diagnostic Checklist

**Services are required for meaningful results.** Most tests depend on PostgreSQL,
object storage, and Redis. Always run `./run_pytest.sh` (which starts services automatically).
Never use `--no-services` unless you are certain the test has no service fixtures.

### Step 1: Reproduce locally

Always start by running the failing test locally with full services:

```bash
# Run all tests with services (default)
./run_pytest.sh

# Run a specific test file
./run_pytest.sh test/test_<name>.py

# Run with visible browser (Playwright debugging)
./run_pytest.sh --headed test/test_<name>.py

# Run specific test file
./run_pytest.sh test/test_<name>.py
```

**Important:** Always use `./run_pytest.sh` (without `--no-services`) for
verification. See [Testing conventions](../conventions/testing.md).

**Outcome:**

- Passes locally → skip to **Step 5** (CI-specific issues)
- Fails locally → **examine artifacts first** (see below), then continue to **Step 2**

**Examine artifacts immediately after failure:**

Artifacts are captured automatically in `test/artifacts/` on every Playwright test
failure. Before diving into code, check them:

```bash
# View screenshot — is the page in the expected state?
open test/artifacts/<test-dir>/test-failed-1.png

# Step through the trace — DOM, network, action timeline
npx playwright show-trace test/artifacts/<test-dir>/trace.zip

# Check browser console for JS errors
cat test/artifacts/<test-dir>/console.log

# Check server logs for callback errors/exceptions
cat test/artifacts/<test-dir>/server.log

# Inspect the DOM at the moment of failure
open test/artifacts/<test-dir>/page.html
```

| Artifact | What it tells you |
|----------|-------------------|
| `test-failed-1.png` | Visual state — is the element on screen? Is an overlay blocking? |
| `trace.zip` | Full action replay — step through clicks, network requests, DOM changes |
| `console.log` | Browser-side errors — failed resource loads, JS exceptions |
| `server.log` | Dash callback logs — exceptions, callback ordering, timing |
| `page.html` | DOM structure — missing elements, wrong IDs, hidden components |

**Common startup failures:**

| Error | Cause | Fix |
|-------|-------|-----|
| `PostgreSQL not available` | DB container failed health check | `docker logs postgres_cosmo_ecosystem` |
| `Object storage did not start` / `Object storage (S3) connectivity check failed` | S3 server unhealthy or unreachable | `docker logs object_storage_cosmo_ecosystem` |
| `Redis not available` | Redis failed health check | `docker logs redis_cosmo_ecosystem` |
| Port already in use | Leftover Docker containers or another process on 5434/9020/6381 | 1. `docker compose down` in the current project first. 2. If persists, tell the user which port is blocked — a sibling project (cosmopolitan, etc.) may be running in parallel and only the user knows which is safe to stop. |
| Docker not running | Docker daemon not started | `sudo systemctl start docker` |

---

### Step 2: Does the test need services?

Check the test function signature for fixture dependencies:

- Has `dash_app` or `celery_worker` parameter → **requires services**
- No service fixtures → can run with `--no-services`

| Requires services | No services needed |
|---|---|
| `test_e2e.py` | `test_env.py` |
| `test_db_manager.py` | `test_html_id_enforcement.py` |
| `test_worker_management.py` | |

Running a service-dependent test with `--no-services` produces connection
failures, not meaningful results. If unsure, run with services.

---

### Step 3: Check if test is flaky

**Symptoms:**

- Test passes sometimes, fails other times
- Timeout errors on `expect().to_be_visible()`
- Different behavior with `--headed` vs headless

**Diagnostic — run 3-5 times:**

```bash
for i in {1..5}; do
    echo "--- Run $i ---"
    ./run_pytest.sh test/test_<name>.py || break
done
```

**Run with visible browser to observe timing:**

```bash
./run_pytest.sh --headed test/test_<name>.py
```

**Common timing fixes:**

| Issue | Fix |
|-------|-----|
| Element not rendered yet | Add `expect(page.locator(f"#{ID}")).to_be_visible()` before interaction |
| Background job not complete | Increase timeout: `expect(...).to_be_enabled(timeout=120000)` |
| Callback race condition | Add `check_all_errors(page)` after navigation |
| Upload not processed | Wait for upload confirmation before next action |

---

### Step 4: Check service health

If tests require services and startup errors occur, verify each service manually.

**PostgreSQL:**

```bash
docker ps | grep postgres_cosmo_ecosystem
docker logs postgres_cosmo_ecosystem
docker exec postgres_cosmo_ecosystem pg_isready -U cosmo_ecosystem_user
```

**Object storage (RustFS):**

```bash
docker ps | grep object_storage_cosmo_ecosystem
docker logs object_storage_cosmo_ecosystem
curl -sf http://localhost:9020/health/ready
```

**Redis:**

```bash
docker ps | grep redis_cosmo_ecosystem
docker logs redis_cosmo_ecosystem
docker exec redis_cosmo_ecosystem redis-cli ping
```

**Clean up and restart:**

When `run_pytest.sh` fails with `PostgreSQL not available` despite the health check
passing, the containers are likely in a stale state from a previous run. **Always
`docker compose down` before retrying** — `run_pytest.sh` only starts containers, it
does not restart them:

```bash
docker compose down
./run_pytest.sh
```

If lingering containers cause port conflicts:

```bash
docker ps -a | grep cosmo-ecosystem
docker compose down --remove-orphans
```

---

### Step 5: CI pipeline issues (passes locally, fails in CI)

**Environment differences:**

| Aspect | Local (`env_test`) | CI (`env_ci`) |
|--------|--------------------------|------------------|
| PostgreSQL | `localhost:5434` | `postgres:5432` |
| Object storage | `localhost:9020` | `object-storage:9000` |
| Redis | `localhost:6381` | `redis:6379` |
| Browser | `--headed` option available | headless only |
| Services | Docker Compose containers | GitLab service containers |

**CI artifacts:** On failure, GitLab archives `test/artifacts/` (7-day retention).
Download from the pipeline job page → "Job artifacts". Contains the same screenshots,
traces, HTML snapshots, console logs, and server logs as local runs.

**Common CI-specific failures:**

1. **Hardcoded hostnames or ports** — use config vars from `src/config.py`, never literals
2. **Hardcoded absolute file paths** — use paths relative to project root (e.g. `test/test_files/data.csv`)
3. **Test assumes visible browser** — remove any `headless=False`; use fixtures, not manual browser setup
4. **Missing test files** — check that files are committed and not in `.gitignore`

**Compare environment files:**

```bash
diff env_test env_test_local
```

**Check CI pipeline configuration:** `.gitlab-ci.yml`

---

### Step 6: Common failure patterns

| Symptom | Likely Cause | Artifact to check | Fix |
|---------|--------------|-------------------|-----|
| `locator.click: Timeout 30000ms exceeded` | Element not visible or overlay blocking | Screenshot, trace | Add `expect().to_be_visible()` before interaction; wait for overlay to close |
| `PostgreSQL not available` | DB container not healthy | — | Check Docker logs, verify ports in `env_test_local` |
| `VIOLATIONS: Found id= usages with string literals` | Literal ID strings in page code | — | Replace with constants from `src/constants/html_ids.py` |
| `ModuleNotFoundError` | Missing dependency or inline import | — | Run `uv sync`; move import to top level |
| `AssertionError` | Test expectation does not match behavior | Screenshot, server.log | Verify whether test or code is wrong |
| `Celery worker failed to start` | Redis broker issue or import error | — | Check Redis is running; check worker imports |
| `Broken image` errors in `check_all_errors` | Leaflet tile images with empty src | page.html | Likely false positive from map tiles — check `check_all_errors()` filter |
| Passes locally, fails CI | Environment differences | CI artifacts | Check config vars vs hardcoded values; compare `env_test` and `env_test_local` |
| Random pass/fail (flaky) | Race condition, insufficient waits | Trace | Add explicit waits with appropriate timeouts |

---

### Step 7: Fix and verify

1. **Make the fix**
2. **Run the specific failing test:**
   ```bash
   ./run_pytest.sh test/test_<name>.py
   ```
3. **Run the full test suite:**
   ```bash
   ./run_pytest.sh
   ```
4. **If timing-related, check for flakiness** (run 3-5 times)
5. **Push and verify CI pipeline passes**

---

## 3. Decision Tree

```
Test failure
│
├── Does it fail locally? (./run_pytest.sh test/test_<name>.py)
│   ├── No → Step 5: CI-specific issues (download CI artifacts)
│   └── Yes ↓
│
├── Examine artifacts in test/artifacts/<test-dir>/
│   ├── Screenshot → visual state, overlay blocking?
│   ├── trace.zip → step through actions (npx playwright show-trace)
│   ├── console.log → JS errors?
│   ├── server.log → callback exceptions?
│   └── page.html → DOM structure correct?
│
├── Does the test need services? (check fixtures)
│   ├── No → run with --no-services, check test logic
│   └── Yes ↓
│
├── Are services healthy? (Step 4: docker logs, health checks)
│   ├── No → fix service startup, clean up containers
│   └── Yes ↓
│
├── Is it flaky? (run 3-5 times)
│   ├── Yes → Step 3: fix timing/waits
│   └── No ↓
│
├── What type of error?
│   ├── locator not found → check HTML IDs, add waits
│   ├── timeout → check screenshot + trace for overlay/loading issues
│   ├── assertion failed → verify test expectations vs actual behavior
│   ├── import error → uv sync, check top-level imports
│   ├── ID enforcement violation → use constants from html_ids.py
│   └── other → check server.log, run with --headed
│
└── Fix → verify specific test → verify full suite → verify CI
```

---

## 4. Key File References

| File | Purpose |
|------|---------|
| `./run_pytest.sh` | Main test runner with service management |
| `test/conftest.py` | Fixtures (`dash_app`, `celery_worker`), `page` override (artifact capture), health checks |
| `test/help_functions_tests.py` | `check_all_errors(page)` utility |
| `test/artifacts/` | Auto-generated on failure: screenshots, traces, HTML, console logs, server logs |
| `env_test_local` | Local test environment (custom ports) |
| `env_test` | CI test environment (service hostnames) |
| `.gitlab-ci.yml` | CI pipeline configuration (uploads `test/artifacts/` on failure) |
| `src/constants/html_ids.py` | HTML ID constants for Playwright locators |
| `docs/conventions/testing.md` | Testing conventions reference |
