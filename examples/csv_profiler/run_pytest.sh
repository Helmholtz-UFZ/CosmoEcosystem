#!/bin/bash

set -e

START_SERVICES=1

# Every worktree gets its own test stack, so several worktrees (and the sister repos)
# can run their suites at the same time. The compose project, and with it the
# container names and volumes, carries a short hash of this directory's absolute
# path: stable for one worktree, so a rerun finds and clears a crashed run's
# leftovers, and different for every other worktree, so a run only ever stops what
# it started. The dev stack from docker-compose.yml (postgres_cosmo_ecosystem etc.)
# is a different project and is never touched.
STACK_ID=$(pwd -P | sha256sum | cut -c1-8)
TEST_PROJECT="cosmo_ecosystem_test_${STACK_ID}"
TEST_POSTGRES="postgres_${TEST_PROJECT}"
TEST_OBJECT_STORAGE="object_storage_${TEST_PROJECT}"
TEST_REDIS="redis_${TEST_PROJECT}"
test_compose() {
    docker compose --project-directory . -p "$TEST_PROJECT" -f docker-compose.yml -f "$OVERRIDE_FILE" "$@"
}

# Cleanup function - restores environment and stops services
cleaning_up() {
    # Restore original .env
    if [ -f .env.bak ]; then
        mv .env.bak .env
    fi

    # Remove only what this run started: the test project's containers and volumes.
    # --no-services never started any, so there is nothing to remove.
    if [ "$START_SERVICES" -eq 1 ]; then
        test_compose down -v >/dev/null 2>&1 || true
    fi
    rm -f "$OVERRIDE_FILE"
}

# Service health check with retry logic
check_service() {
    local check_command="$1"
    local service_name="$2"
    local max_retries=10
    local retry_count=0

    until eval "$check_command"; do
        if [ $retry_count -ge $max_retries ]; then
            echo "FAIL: ${service_name} did not start after ${max_retries} attempts"
            cleaning_up
            exit 1
        fi
        sleep 1
        retry_count=$((retry_count + 1))
    done
    echo "  ${service_name} ready"
}

# Help message
show_help() {
    echo "Usage: ./run_pytest.sh [OPTIONS] [TEST_PATH]"
    echo ""
    echo "The ONLY way to run tests. Do NOT run pytest directly."
    echo ""
    echo "This script manages the test environment: backs up .env, starts Docker"
    echo "services, runs pytest, then restores .env and stops services on exit."
    echo "The services run as compose project ${TEST_PROJECT} (one per worktree)"
    echo "on free host ports picked at start, so worktrees can run their suites in"
    echo "parallel; the dev stack's containers are never touched."
    echo "With --no-services the ports from env_test apply."
    echo ""
    echo "Options:"
    echo "  --headed          Run browser tests with visible browser (for debugging)"
    echo "  --no-services     Skip Docker service start/stop (services must already be running)."
    echo "  --no-artifacts    Disable Playwright artifact capture (screenshots, traces)"
    echo "  --keep-artifacts  Keep artifacts from previous runs (default: clear on each run)"
    echo "  -v, --verbose     Show full pytest output (default: minimal, logs go to artifacts)"
    echo "  -h, --help        Show this help message"
    echo ""
    echo "Test Selection:"
    echo "  [TEST_PATH]       Specific test file, directory, or pytest node ID (optional)."
    echo "                    Passed directly to pytest as the last argument."
    echo ""
    echo "Examples:"
    echo "  ./run_pytest.sh                                        # Run all tests"
    echo "  ./run_pytest.sh --headed                               # Visible browser"
    echo "  ./run_pytest.sh test/test_e2e.py                       # Specific file"
    echo "  ./run_pytest.sh test/test_e2e.py::test_full_procedure  # Specific test"
    echo ""
    echo "Artifacts (on failure): screenshots, traces, HTML in test/artifacts/"
    echo "Full pytest output: test/artifacts/pytest_output.log"
    echo "View traces: npx playwright show-trace test/artifacts/<test-name>/trace.zip"
    exit 0
}

# Parse command line arguments
HEADED=false
ARTIFACTS=true
KEEP_ARTIFACTS=false
VERBOSE=false
TEST_PATH=""

while [[ $# -gt 0 ]]; do
    case $1 in
    --headed)
        HEADED=true
        shift
        ;;
    --no-services)
        START_SERVICES=0
        shift
        ;;
    --no-artifacts)
        ARTIFACTS=false
        shift
        ;;
    --keep-artifacts)
        KEEP_ARTIFACTS=true
        shift
        ;;
    -v | --verbose)
        VERBOSE=true
        shift
        ;;
    -h | --help)
        show_help
        ;;
    *)
        TEST_PATH="$1"
        shift
        ;;
    esac
done

# Arguments are parsed; from here on the run owns state worth cleaning up.
OVERRIDE_FILE=$(mktemp --suffix=.yml)
cat > "$OVERRIDE_FILE" <<EOF
services:
  postgres:
    container_name: ${TEST_POSTGRES}
  object-storage:
    container_name: ${TEST_OBJECT_STORAGE}
  redis:
    container_name: ${TEST_REDIS}
EOF
trap cleaning_up EXIT

# Backup existing .env
if [ -f .env ]; then
    mv .env .env.bak
fi

# Use test environment configuration
cp env_test .env

if [ "$START_SERVICES" -eq 1 ]; then
    # Ask the OS for free host ports instead of using env_test's fixed slot, which
    # another worktree's test stack may hold. All five sockets are open at once, so
    # the ports are distinct. Between closing them here and compose binding them
    # another process could take one; that race is accepted, compose then fails
    # loudly with "port is already allocated".
    read -r FLASK POSTGRES REDIS OBJECT_STORAGE OBJECT_STORAGE_CONSOLE < <(python3 -c '
import socket
socks = [socket.socket() for _ in range(5)]
# "" = all interfaces, as compose publishes (0.0.0.0): a port that is free only on
# loopback would still collide there.
for s in socks:
    s.bind(("", 0))
print(*(s.getsockname()[1] for s in socks))
') || {
        # read sees EOF when python3 fails; without this set -e exits silently.
        echo "FAIL: could not pick free ports"
        exit 1
    }
    # Appended, so these win over env_test's values in the same file (python-dotenv
    # and compose both take the last assignment of a key). The suite runs on the
    # host, so the app-facing port and the published host port are the same number.
    # FLASK_PORT is where the e2e Dash server binds.
    cat >>.env <<EOF

### Per-run ports, written by run_pytest.sh ###
FLASK_PORT=${FLASK}
FLASK_HOST_PORT=${FLASK}
WEB_OUTSIDE_URL="http://localhost:${FLASK}"
POSTGRES_PORT="${POSTGRES}"
POSTGRES_HOST_PORT=${POSTGRES}
REDIS_PORT="${REDIS}"
REDIS_HOST_PORT=${REDIS}
OBJECT_STORAGE_HOST="http://localhost:${OBJECT_STORAGE}"
OBJECT_STORAGE_HOST_PORT=${OBJECT_STORAGE}
OBJECT_STORAGE_CONSOLE_HOST_PORT=${OBJECT_STORAGE_CONSOLE}
EOF
    # check_parallel_runs.sh parses this line to find the run's project: keep the format.
    echo "Compose project: ${TEST_PROJECT}"
    echo "Ports: flask ${FLASK}, postgres ${POSTGRES}, redis ${REDIS}," \
        "object storage ${OBJECT_STORAGE} (console ${OBJECT_STORAGE_CONSOLE})"

    # Clear leftovers of a crashed earlier test run (test project only)
    test_compose down -v 2>/dev/null || true

    # Start services (quiet output)
    echo "Starting services: postgres, object-storage, redis"
    test_compose up postgres object-storage redis -d --quiet-pull

    # Wait for services with retry logic
    check_service 'docker exec "$TEST_POSTGRES" pg_isready -q 2>/dev/null' "PostgreSQL"
    # The compose healthcheck owns the server-specific probe; this only reads its verdict.
    check_service 'docker inspect -f "{{.State.Health.Status}}" "$TEST_OBJECT_STORAGE" 2>/dev/null | grep -qx healthy' "Object storage"
    check_service 'docker exec "$TEST_REDIS" redis-cli ping 2>/dev/null | grep -q PONG' "Redis"
else
    echo "Skipping service management (assuming services already running)"
fi

# Clear previous artifacts unless --keep-artifacts is set
if [ "$KEEP_ARTIFACTS" = false ] && [ -d test/artifacts ]; then
    rm -rf test/artifacts/*
fi
mkdir -p test/artifacts

# Build pytest command dynamically based on flags
PYTEST_CMD="uv run pytest"

# Add artifact flags (enabled by default)
if [ "$ARTIFACTS" = true ]; then
    PYTEST_CMD="$PYTEST_CMD --screenshot only-on-failure --tracing retain-on-failure --output test/artifacts"
fi

# Add --no-services flag if needed
if [ "$START_SERVICES" -eq 0 ]; then
    PYTEST_CMD="$PYTEST_CMD --no-services"
fi

# Add --headed flag if needed
if [ "$HEADED" = true ]; then
    PYTEST_CMD="$PYTEST_CMD --headed"
fi

# Add test path if specified
if [ -n "$TEST_PATH" ]; then
    PYTEST_CMD="$PYTEST_CMD $TEST_PATH"
fi

# Run pytest — output goes to temp file, moved into artifacts after Playwright is done.
# Playwright cleans --output dir when all tests pass, so writing there during the run
# would lose the log.
TMP_LOG=$(mktemp)
LOG_FILE="test/artifacts/pytest_output.log"

set +e
if [ "$VERBOSE" = true ]; then
    echo "Running: $PYTEST_CMD"
    bash -c "$PYTEST_CMD" 2>&1 | tee "$TMP_LOG"
    PYTEST_EXIT=${PIPESTATUS[0]}
else
    echo "Running tests (logs: $LOG_FILE) ..."
    bash -c "$PYTEST_CMD" > "$TMP_LOG" 2>&1
    PYTEST_EXIT=$?
fi

mkdir -p test/artifacts
mv "$TMP_LOG" "$LOG_FILE"

if [ "$VERBOSE" = false ]; then
    echo ""
    grep -E "^(FAILED|ERROR|=)" "$LOG_FILE" | tail -20 || true
    echo "Full output: $LOG_FILE"
fi
exit $PYTEST_EXIT
