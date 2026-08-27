#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

printf '==> Checking Git whitespace errors\n'
git diff --check

printf '==> Checking shell syntax\n'
while IFS= read -r -d '' script; do
  bash -n "$script"
done < <(find scripts -type f -name '*.sh' -print0 | sort -z)

printf '==> Compiling Python files\n'
python3 -m compileall -q custom-addons scripts

printf '==> Verifying the immutable canonical addon baseline\n'
python3 scripts/validate_legacy_addon_baseline.py

printf '==> Validating Odoo manifests\n'
python3 scripts/validate_manifests.py

printf '==> Validating the Middleware and Odoo write boundary\n'
python3 scripts/validate_integration_boundary.py

printf '==> Reviewing every custom Odoo module\n'
python3 scripts/review_modules.py --strict

printf '==> Validating Codestra login, administrator, and database controls\n'
python3 scripts/validate_codestra_readiness.py

printf '==> Validating the corporate call-center workstream contract\n'
python3 scripts/validate_call_center_workstreams.py
