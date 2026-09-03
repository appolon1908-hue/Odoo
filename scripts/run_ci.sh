#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -z "${PYTHONPYCACHEPREFIX:-}" ]]; then
  CI_PYCACHE_DIR="$(mktemp -d)"
  export PYTHONPYCACHEPREFIX="$CI_PYCACHE_DIR"
  trap 'rm -rf -- "$CI_PYCACHE_DIR"' EXIT
fi

printf '==> Checking Git whitespace errors\n'
git diff --check

printf '==> Checking shell syntax\n'
while IFS= read -r -d '' script; do
  bash -n "$script"
done < <(find scripts -type f -name '*.sh' -print0 | sort -z)

UPSTREAM_SYNC_INITIALIZED=NO
if [[ -e config/upstream-sync-state.json || -e upstream/codestra-odoo-addons ]]; then
  UPSTREAM_SYNC_INITIALIZED=YES
fi
for treeish in HEAD^ origin/main; do
  if git cat-file -e "$treeish:config/upstream-sync-state.json" 2>/dev/null; then
    UPSTREAM_SYNC_INITIALIZED=YES
  fi
done
if [[ "$UPSTREAM_SYNC_INITIALIZED" == YES ]]; then
  [[ -f config/upstream-sync-state.json ]] || {
    printf '%s\n' 'initialized upstream sync state is missing' >&2
    exit 1
  }
  [[ -d upstream/codestra-odoo-addons ]] || {
    printf '%s\n' 'initialized upstream source snapshot is missing' >&2
    exit 1
  }
  printf '==> Verifying recorded upstream synchronization state\n'
  python3 -I scripts/sync_codestra_odoo_addons.py --verify-state
fi

printf '==> Compiling Python files\n'
python3 -I -X pycache_prefix="$PYTHONPYCACHEPREFIX" -m compileall -q custom-addons scripts tests/security

printf '==> Verifying the immutable canonical addon baseline\n'
python3 -I scripts/validate_legacy_addon_baseline.py

printf '==> Validating Odoo manifests\n'
python3 -I scripts/validate_manifests.py

printf '==> Validating the Middleware and Odoo write boundary\n'
python3 -I scripts/validate_integration_boundary.py

printf '==> Validating hardened database and generic-proxy boundary controls\n'
python3 -I scripts/validate_integration_boundary_hardening.py

printf '==> Validating the four-repository platform control plane\n'
python3 -I scripts/validate_platform_control_plane.py

printf '==> Validating the shared Middleware-to-Odoo HMAC vector\n'
python3 -I scripts/validate_odoo_hmac_vector.py

printf '==> Reviewing every custom Odoo module\n'
python3 -I scripts/review_modules.py --strict

printf '==> Validating Codestra login, administrator, and database controls\n'
python3 -I scripts/validate_codestra_readiness.py

printf '==> Validating the corporate call-center workstream contract\n'
python3 -I scripts/validate_call_center_workstreams.py

printf '==> Validating complete mission module coverage\n'
python3 -I scripts/validate_mission_coverage.py

printf '==> Validating mission security and closed capabilities\n'
python3 -I scripts/validate_mission_security.py

printf '==> Validating canonical API inventory\n'
python3 -I scripts/validate_api_contracts.py

printf '==> Validating migration policies\n'
python3 -I scripts/validate_migration_contracts.py

printf '==> Validating browser, load, security, and migration evidence contracts\n'
python3 -I scripts/validate_test_evidence_contracts.py

printf '==> Running source-level mission contract tests\n'
python3 -I scripts/run_isolated_source_tests.py

printf '==> Validating release-candidate policy\n'
python3 -I scripts/validate_release_policy.py
