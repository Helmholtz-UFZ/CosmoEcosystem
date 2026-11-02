#!/bin/bash
# Acceptance check: two worktrees of this repo run ./run_pytest.sh at the same time.
#
# Passes when both runs are green and, afterwards, no container or volume of either
# run's compose project is left. Run it by hand (or let an agent run it) after changing
# run_pytest.sh; it is not a CI job, because CI has no parallel worktrees.
#
# It creates a throwaway detached worktree of HEAD next to the others
# (<main clone>.wt/parallel-check-probe), so only committed changes take part on that
# side, and removes it with `git worktree remove` at the end.
#
# Usage: ./check_parallel_runs.sh [TEST_PATHS]
#   TEST_PATHS (one argument, space-separated) defaults to test_env followed by the
#   e2e suite. The e2e suite starts the Dash server and the Celery worker and goes
#   through Postgres, object storage and Redis, so a shared port or container on any
#   of them breaks it. test_env comes first because it loads every env file: if it
#   leaked env_test's slot ports into the session, the worker started after it would
#   go to the wrong Redis.

set -u

SUBSET="${1:-test/test_env.py test/test_e2e.py}"
EXAMPLE_DIR="examples/csv_profiler"

HERE=$(cd "$(dirname "$0")" && pwd -P)
REPO_ROOT=$(git -C "$HERE" rev-parse --show-toplevel)
# The common git dir is <main clone>/.git, also when called from a worktree.
MAIN_CLONE=$(dirname "$(git -C "$HERE" rev-parse --path-format=absolute --git-common-dir)")
PROBE="${MAIN_CLONE}.wt/parallel-check-probe"
LOG_DIR=$(mktemp -d)

declare -A PIDS
remove_probe() {
    # On an abort (Ctrl-C) the two runs are still going: stop them first, so their
    # own EXIT trap removes their stacks before the probe worktree disappears.
    for pid in "${PIDS[@]}"; do
        pkill -TERM -P "$pid" 2>/dev/null
    done
    wait
    git -C "$REPO_ROOT" worktree remove --force "$PROBE" 2>/dev/null || true
}
trap remove_probe EXIT

remove_probe
git -C "$REPO_ROOT" worktree add --detach "$PROBE" HEAD >/dev/null || exit 1

# Sync both venvs first, so the two runs reach their services at the same time
# instead of one still installing packages while the other is already done.
for dir in "$REPO_ROOT" "$PROBE"; do
    (cd "$dir/$EXAMPLE_DIR" && uv sync --quiet) || exit 1
done

echo "Running '$SUBSET' in two worktrees at once (logs: $LOG_DIR)"
(cd "$REPO_ROOT/$EXAMPLE_DIR" && ./run_pytest.sh "$SUBSET" >"$LOG_DIR/a.log" 2>&1) &
PIDS[a]=$!
(cd "$PROBE/$EXAMPLE_DIR" && ./run_pytest.sh "$SUBSET" >"$LOG_DIR/b.log" 2>&1) &
PIDS[b]=$!

FAILED=0
declare -A PROJECTS
for run in a b; do
    wait "${PIDS[$run]}"
    exit_code=$?
    log="$LOG_DIR/$run.log"
    # run_pytest.sh prints "Compose project: <name>" at start.
    project=$(sed -n 's/^Compose project: //p' "$log")
    PROJECTS[$run]=$project
    echo "--- run $run: exit $exit_code, project '$project'"
    if [ "$exit_code" -ne 0 ]; then
        FAILED=1
        tail -25 "$log"
    fi
    if [ -z "$project" ]; then
        echo "FAIL: run $run did not print its compose project"
        FAILED=1
        continue
    fi
    label="label=com.docker.compose.project=$project"
    leftovers=$(docker ps -aq --filter "$label"; docker volume ls -q --filter "$label")
    if [ -n "$leftovers" ]; then
        echo "FAIL: run $run left containers or volumes of $project behind"
        FAILED=1
    fi
done

if [ -n "${PROJECTS[a]}" ] && [ "${PROJECTS[a]}" = "${PROJECTS[b]}" ]; then
    echo "FAIL: both runs used compose project ${PROJECTS[a]}"
    FAILED=1
fi

if [ "$FAILED" -eq 0 ]; then
    echo "PASS: both runs green, nothing left behind"
else
    echo "FAIL (full logs: $LOG_DIR)"
fi
exit $FAILED
