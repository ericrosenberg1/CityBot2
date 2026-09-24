#!/usr/bin/env bash
# Runs infra-leak-guard when it is installed on this machine. The guard and its
# pattern list live outside this public repo on purpose (the patterns name the
# private infrastructure they protect). Point INFRA_LEAK_GUARD at it if it is
# not in the default location. Usage: infra-leak-guard.sh --pre-commit|--pre-push
set -euo pipefail
guard="${INFRA_LEAK_GUARD:-$HOME/Code/_tools/infra-leak-guard/infra-leak-guard}"
if [ ! -x "$guard" ]; then
  echo "infra-leak-guard: not installed here, skipping ($guard)" >&2
  exit 0
fi
exec "$guard" "$@"
