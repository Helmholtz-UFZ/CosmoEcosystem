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
# Usage: ./check_parallel_runs.sh [TEST_PATH]
#   TEST_PATH defaults to the e2e suite: it starts the Dash server and the Celery
#   worker and goes through Postgres, object storage and Redis, so a shared port or
#   container on any of them breaks it.

set -u

SUBSET="${1:-test/test_e2e.py}"
EXAMPLE_DIR="examples/csv_profiler"

HERE=$(cd "$(dirname "$0")" && pwd -P)
REPO_ROOT=$(git -C "$HERE" rev-parse --show-toplevel)
# The common git dir is <main clone>/.git, also when called from a worktree.
MAIN_CLONE=$(dirname "$(git -C "$HERE" rev-parse --path-format=absolute --git-common-dir)")
PROBE="${MAIN_CLONE}.wt/parallel-check-probe"
LOG_DIR=$(mktemp -d)

remove_probe() {
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
PID_A=$!
(cd "$PROBE/$EXAMPLE_DIR" && ./run_pytest.sh "$SUBSET" >"$LOG_DIR/b.log" 2>&1) &
PID_B=$!
wait $PID_A
EXIT_A=$?
wait $PID_B
EXIT_B=$?

FAILED=0
for run in a b; do
    exit_var="EXIT_${run^^}"
    log="$LOG_DIR/$run.log"
    # run_pytest.sh prints "Compose project: <name>" at start.
    project=$(sed -n 's/^Compose project: //p' "$log")
    echo "--- run $run: exit ${!exit_var}, project '${project}'"
    if [ "${!exit_var}" -ne 0 ]; then
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

PROJECT_A=$(sed -n 's/^Compose project: //p' "$LOG_DIR/a.log")
PROJECT_B=$(sed -n 's/^Compose project: //p' "$LOG_DIR/b.log")
if [ -n "$PROJECT_A" ] && [ "$PROJECT_A" = "$PROJECT_B" ]; then
    echo "FAIL: both runs used compose project $PROJECT_A"
    FAILED=1
fi

if [ "$FAILED" -eq 0 ]; then
    echo "PASS: both runs green, nothing left behind"
else
    echo "FAIL (full logs: $LOG_DIR)"
fi
exit $FAILED
