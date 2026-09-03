#!/usr/bin/env bash
# Local gates. Replaces .github/workflows/ci.yml (GitHub Actions retired
# 2026-09-03). Run by .githooks/pre-push, or by hand: scripts/ci-gates.sh
#
# Scope note: the workflow ran "ruff check ." over the whole repo. That is
# currently 387 findings of pre-existing style debt (UP006 annotations, import
# sorting, and similar) which built up while Actions was switched off, so a
# whole-repo gate would block every push on code nobody is touching. This gates
# CHANGED files instead, the usual way to adopt a linter on a repo with debt:
# new and edited code must be clean, the backlog is reported and not blocking.
# Run "uvx ruff check ." to see the full backlog, or pass --all here.
set -euo pipefail
cd "$(dirname "$0")/.."

# Resolve ruff without assuming a global install: the deleted workflow did
# "pip install ruff" on a fresh runner every time. Prefer a repo venv, then
# whatever is on PATH, then uvx (no install needed).
RUFF=""
for c in ./venv/bin/ruff ./.venv/bin/ruff; do [ -x "$c" ] && RUFF="$c" && break; done
[ -n "$RUFF" ] || command -v ruff >/dev/null 2>&1 && RUFF="${RUFF:-ruff}"
[ -n "$RUFF" ] || { command -v uvx >/dev/null 2>&1 && RUFF="uvx ruff"; }
[ -n "$RUFF" ] || { echo "ci-gates: no ruff found (try: uv tool install ruff)"; exit 1; }

if [ "${1:-}" = "--all" ]; then
  echo "==> ruff check (whole repo)"
  $RUFF check . --ignore E402
  echo "==> ruff format --check (whole repo)"
  $RUFF format --check .
else
  # bash 3.2 on macOS has no mapfile, so collect into a temp file.
  base="$(git merge-base @{u} HEAD 2>/dev/null || echo HEAD~1)"
  changed="$(mktemp)"; trap 'rm -f "$changed"' EXIT
  git diff --name-only --diff-filter=ACM "$base" HEAD -- '*.py' > "$changed"
  n=$(wc -l < "$changed" | tr -d ' ')
  if [ "$n" -eq 0 ]; then
    echo "==> no changed .py files, skipping ruff"
  else
    echo "==> ruff check ($n changed file(s))"
    xargs $RUFF check --ignore E402 < "$changed"
    echo "==> ruff format --check (changed files)"
    xargs $RUFF format --check < "$changed"
  fi
  backlog=$($RUFF check . --ignore E402 --statistics 2>/dev/null | awk '{s+=$1} END{print s+0}' || true)
  if [ "${backlog:-0}" -gt 0 ]; then
    echo "    note: ${backlog} pre-existing findings repo-wide (scripts/ci-gates.sh --all)"
  fi
fi

echo "==> py_compile"
find . -name "*.py" -not -path "./venv/*" -not -path "./.venv/*" -print0 | xargs -0 python3 -m py_compile

echo "==> gates passed"
