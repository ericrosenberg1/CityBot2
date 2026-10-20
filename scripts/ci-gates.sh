#!/usr/bin/env bash
# Local gates. Replaces .github/workflows/ci.yml (GitHub Actions retired
# 2026-09-03). Run by .githooks/pre-push, or by hand: scripts/ci-gates.sh
#
# Ruff covers the whole repo. The style backlog that once limited it to
# changed files was cleared on 2026-10-20, so keep it at zero.
#
# The ruff check below names its rules instead of riding ruff's defaults.
# Ruff 0.16.0 widened the default set from E4/E7/E9/F to 413 rules, so the
# same command that reports zero here reports 13 DTZ findings on 0.16.x and
# the pre-push hook starts refusing every push. Those 13 are not safe to
# clear by adding a tz argument: the rate limiter in social_media/utils.py
# stores naive isoformat() strings in sqlite and compares them as text, so
# mixing aware rows in makes can_post() raise TypeError on the rows already
# there. Widening the set is a deliberate choice, not an upgrade side effect.
set -euo pipefail
cd "$(dirname "$0")/.."

# Resolve ruff without assuming a global install: the deleted workflow did
# "pip install ruff" on a fresh runner every time. Prefer a repo venv, then
# whatever is on PATH, then uvx (no install needed). The uvx fallback asks for
# this version so a fresh machine gets the same formatter as requirements-dev.
RUFF_PIN="0.15.14"
RUFF=()
for c in ./venv/bin/ruff ./.venv/bin/ruff; do
  if [ -x "$c" ]; then RUFF=("$c"); break; fi
done
if [ ${#RUFF[@]} -eq 0 ] && command -v ruff >/dev/null 2>&1; then RUFF=(ruff); fi
if [ ${#RUFF[@]} -eq 0 ] && command -v uvx >/dev/null 2>&1; then RUFF=(uvx "ruff@${RUFF_PIN}"); fi
if [ ${#RUFF[@]} -eq 0 ]; then echo "ci-gates: no ruff found (try: uv tool install ruff)"; exit 1; fi

echo "==> ruff check"
"${RUFF[@]}" check . --select E4,E7,E9,F --ignore E402
echo "==> ruff format --check"
"${RUFF[@]}" format --check .

echo "==> py_compile"
find . -name "*.py" -not -path "./venv/*" -not -path "./.venv/*" -print0 | xargs -0 python3 -m py_compile

# Tests need the app's dependencies, so use a Python that has them:
# $CITYBOT_PYTHON, then a repo venv. requirements-dev.txt is not enough on its
# own: blueskysocial is left out of it on purpose (see requirements.txt), and
# without it tests/test_queue.py and tests/test_social.py fail to import. Build
# the venv the way the Dockerfile and install.sh do:
#   pip install -r requirements-dev.txt
#   pip install --no-deps blueskysocial==2.1.0
PY=""
for c in "${CITYBOT_PYTHON:-}" ./venv/bin/python ./.venv/bin/python; do
  [ -n "$c" ] && [ -x "$c" ] && "$c" -c "import pytest, fastapi" 2>/dev/null && PY="$c" && break
done
if [ -n "$PY" ]; then
  echo "==> pytest"
  SENTRY_DSN="" "$PY" -m pytest -q -p no:cacheprovider tests
else
  echo "ci-gates: no Python with pytest and the app deps (set CITYBOT_PYTHON, or build ./venv from requirements-dev.txt plus --no-deps blueskysocial==2.1.0)"
  exit 1
fi

echo "==> gates passed"
