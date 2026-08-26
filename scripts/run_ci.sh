#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

printf '==> Checking Git whitespace errors\n'
git diff --check

printf '==> Checking shell syntax\n'
bash -n scripts/run_ci.sh

printf '==> Compiling Python files\n'
python3 -m compileall -q custom-addons scripts

printf '==> Validating Odoo manifests\n'
python3 scripts/validate_manifests.py

printf '==> Validating the Middleware and Odoo write boundary\n'
python3 scripts/validate_integration_boundary.py
