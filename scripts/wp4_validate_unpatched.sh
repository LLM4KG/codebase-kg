#!/bin/bash
# WP4: check that a task's test FAILS on the unpatched pinned checkout
# (the reference-patch PASS side is covered by `pipeline pilot calibrate`,
# which runs the reference patch through the full harness).
#
# Usage: scripts/wp4_validate_unpatched.sh P4 [--patched]
#   --patched  also apply the reference patch (quick check without the harness)
# Runs the task's test file in the project's harness image, exactly as the
# harness mounts it, with the project's test command. Exit code = jest's.
set -euo pipefail
TASK="$1"; MODE="${2:-}"
YAML="tasks/pilot/${TASK}.yaml"
PROJECT=$(grep '^project_id:' "$YAML" | awk '{print $2}')
TEST_DEST=$(awk '/^test_files:/{getline; sub(/^ *- */,""); print; exit}' "$YAML")
TEST_SRC="tasks/pilot/tests/$(basename "$TEST_DEST")"
PATTERN=$(basename "$TEST_DEST" | sed 's/\.test\..*//')
case "$PROJECT" in
  react-shopping-cart)
    IMAGE=codebase-kg-harness/react-shopping-cart:pilot
    CMD="CI=true npm test -- --testPathPattern=$PATTERN" ;;
  takenote)
    IMAGE=codebase-kg-harness/takenote:pilot
    CMD="npx jest --config config/jest.config.js --testPathPattern=$PATTERN" ;;
  *) echo "unknown project $PROJECT" >&2; exit 2 ;;
esac
APPLY=""
MOUNTS=(-v "$(realpath "$TEST_SRC"):/app/$TEST_DEST:ro")
if [ "$MODE" = "--patched" ]; then
  MOUNTS+=(-v "$(realpath "tasks/pilot/patches/${TASK}.diff"):/tmp/ref.diff:ro")
  APPLY="git apply /tmp/ref.diff && "
fi
echo "== $TASK ($PROJECT) ${MODE:-unpatched}: $CMD"
docker run --rm --entrypoint bash "${MOUNTS[@]}" "$IMAGE" -c "cd /app && ${APPLY}${CMD}"
