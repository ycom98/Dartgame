#!/usr/bin/env bash
# Dart Room test entry points.
#
#   scripts/test.sh py       Python unittest suite (tests/test_*.py)
#   scripts/test.sh browser  Every runnable Playwright suite (tests/*.cjs)
#   scripts/test.sh browser --record
#                            Same, but write screenshots/JSON into the committed qa-artifacts/
#
# Browser suites write their screenshots and result JSON to $DART_QA_ARTIFACTS. Without --record
# this defaults to test-output/browser-<timestamp>/ (gitignored), so a test run never overwrites
# committed evidence.
#
# Environment overrides:
#   DART_PYTHON  Python interpreter (default: <root>/.venv/bin/python)
#   DART_CHROME  Chrome/Chromium executable for Playwright (default: Playwright's bundled Chromium)
#   DART_QA_ARTIFACTS  Browser evidence directory (overrides the default; --record wins)
#
# Servers started by the tests save their match to a throw-away DART_STATE_FILE (M1-16), never to the
# real .local/state/match.json; each browser suite gets its own.
#
# Both entry points exit non-zero if any test or suite fails.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 2

PYTHON="${DART_PYTHON:-$ROOT/.venv/bin/python}"
export DART_PYTHON="$PYTHON"

if [ ! -x "$PYTHON" ]; then
  echo "Python not found at $PYTHON. Create it with:" >&2
  echo "  python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt" >&2
  exit 2
fi

STATE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/dart-test-state.XXXXXX")"
trap 'rm -rf "$STATE_ROOT"' EXIT

run_python() {
  DART_STATE_FILE="$STATE_ROOT/python/match.json" "$PYTHON" -B -m unittest discover -s tests "$@"
}

run_browser() {
  if [ "${1:-}" = "--record" ]; then
    export DART_QA_ARTIFACTS="$ROOT/qa-artifacts"
  elif [ -z "${DART_QA_ARTIFACTS:-}" ]; then
    export DART_QA_ARTIFACTS="$ROOT/test-output/browser-$(date +%Y%m%d-%H%M%S)"
  fi
  echo "Browser evidence: $DART_QA_ARTIFACTS"
  # Helper modules (not runnable suites) are skipped here.
  local skip=" manual_qa_common.cjs qa_output.cjs "
  local failed=()
  local passed=()
  local suite name status
  for suite in tests/*.cjs; do
    name="$(basename "$suite")"
    case "$skip" in *" $name "*) continue ;; esac
    echo "=== $name"
    DART_STATE_FILE="$STATE_ROOT/$name/match.json" node "$suite"
    status=$?
    if [ "$status" -eq 0 ]; then
      passed+=("$name")
      echo "=== PASS $name"
    else
      failed+=("$name")
      echo "=== FAIL $name (exit $status)"
    fi
  done
  echo
  echo "Browser suites: ${#passed[@]} passed, ${#failed[@]} failed"
  local f
  for f in "${failed[@]+"${failed[@]}"}"; do
    echo "  FAILED: $f"
  done
  [ "${#failed[@]}" -eq 0 ]
}

case "${1:-}" in
  py)
    shift
    run_python "$@"
    ;;
  browser)
    shift
    run_browser "$@"
    ;;
  *)
    echo "Usage: scripts/test.sh py | browser [--record]" >&2
    exit 2
    ;;
esac
