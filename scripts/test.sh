#!/usr/bin/env bash
# Dart Room test entry points.
#
#   scripts/test.sh py       Python unittest suite (tests/test_*.py)
#   scripts/test.sh browser  Every runnable Playwright suite (tests/*.cjs)
#
# Environment overrides:
#   DART_PYTHON  Python interpreter (default: <root>/.venv/bin/python)
#   DART_CHROME  Chrome/Chromium executable for Playwright (default: Playwright's bundled Chromium)
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

run_python() {
  "$PYTHON" -B -m unittest discover -s tests "$@"
}

run_browser() {
  # Helper modules (not runnable suites) are skipped here.
  local skip=" manual_qa_common.cjs "
  local failed=()
  local passed=()
  local suite name status
  for suite in tests/*.cjs; do
    name="$(basename "$suite")"
    case "$skip" in *" $name "*) continue ;; esac
    echo "=== $name"
    node "$suite"
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
    run_browser
    ;;
  *)
    echo "Usage: scripts/test.sh py|browser" >&2
    exit 2
    ;;
esac
