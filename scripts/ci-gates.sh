#!/usr/bin/env bash
# Local gates. Replaces .github/workflows/ci.yml (GitHub Actions retired
# 2026-09-03). Run by .githooks/pre-push, or by hand: scripts/ci-gates.sh
#
# Ruff covers the whole repo. The style backlog that once limited it to
# changed files was cleared on 2026-10-20, so keep it at zero.
set -euo pipefail
cd "$(dirname "$0")/.."

# Resolve ruff without assuming a global install: the deleted workflow did
# "pip install ruff" on a fresh runner every time. Prefer a repo venv, then
# whatever is on PATH, then uvx (no install needed).
RUFF=()
for c in ./venv/bin/ruff ./.venv/bin/ruff; do
  if [ -x "$c" ]; then RUFF=("$c"); break; fi
done
if [ ${#RUFF[@]} -eq 0 ] && command -v ruff >/dev/null 2>&1; then RUFF=(ruff); fi
if [ ${#RUFF[@]} -eq 0 ] && command -v uvx >/dev/null 2>&1; then RUFF=(uvx ruff); fi
if [ ${#RUFF[@]} -eq 0 ]; then echo "ci-gates: no ruff found (try: uv tool install ruff)"; exit 1; fi

echo "==> ruff check"
"${RUFF[@]}" check . --ignore E402
echo "==> ruff format --check"
"${RUFF[@]}" format --check .

echo "==> py_compile"
find . -name "*.py" -not -path "./venv/*" -not -path "./.venv/*" -print0 | xargs -0 python3 -m py_compile

# Tests need the app's dependencies, so use a Python that has them:
# $CITYBOT_PYTHON, then a repo venv. Install with: pip install -r requirements-dev.txt
PY=""
for c in "${CITYBOT_PYTHON:-}" ./venv/bin/python ./.venv/bin/python; do
  [ -n "$c" ] && [ -x "$c" ] && "$c" -c "import pytest, fastapi" 2>/dev/null && PY="$c" && break
done
if [ -n "$PY" ]; then
  echo "==> pytest"
  SENTRY_DSN="" "$PY" -m pytest -q -p no:cacheprovider tests
else
  echo "ci-gates: no Python with pytest and the app deps (set CITYBOT_PYTHON or build ./venv from requirements-dev.txt)"
  exit 1
fi

echo "==> gates passed"
