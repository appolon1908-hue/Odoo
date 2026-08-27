#!/usr/bin/env python3
"""Generate a truthful blocked-by-default mission report for a source candidate."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def command(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()


def optional_command(*args: str) -> str:
    try:
        return command(*args)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "UNKNOWN"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source_sha = command("git", "rev-parse", "HEAD")
    baseline = optional_command("git", "merge-base", "HEAD", "origin/main")
    coverage = json.loads(
        (ROOT / "config" / "call-center-module-coverage.json").read_text(encoding="utf-8")
    )
    endpoints = json.loads(
        (ROOT / "tests" / "contracts" / "canonical-endpoints.json").read_text(encoding="utf-8")
    )
    modules = coverage["coverage"]
    schema_count = sum(item["implementation_type"] == "schema" for item in modules)
    implemented_routes = sum(
        item["implementation_status"] == "implemented-in-canonical-addon"
        for item in endpoints["endpoints"]
    )
    source_tests = os.environ.get("SOURCE_TESTS_STATUS", "NOT_RECORDED")
    blockers = [
        "stacked pull requests are not independently approved and merged",
        "connector-created commits are not cryptographically signed",
        "database upgrade, interrupted migration, backup, and restore evidence is absent",
        "canonical API adapters and Kong policies remain incomplete or uncertified",
        "Keycloak, mTLS, VICIdial, browser, load, recovery, and cross-tenant runtime evidence is absent",
        "no signed container image digest, complete image SBOM, vulnerability evidence, or provenance exists",
        "isolated staging, rollback rehearsal, canary, one-hour soak, and one-business-day soak have not run",
        "email, SMS, callbacks, n8n, live call control, and PSTN dialing remain disabled",
    ]
    lines = [
        f"BASELINE_COMMIT={baseline}",
        f"SOURCE_BRANCH_COMMIT={source_sha}",
        "FINAL_PROTECTED_COMMIT=BLOCKED_NOT_MERGED",
        "RELEASE_IMAGE_DIGEST=BLOCKED_NOT_BUILT",
        "ODOO_VERSION=19",
        f"MODULES_CREATED={len(modules)}_MISSION_MODULES_INCLUDING_{schema_count}_MODEL_OWNING_MODULES",
        "MODULES_UPGRADED=0_SOURCE_ONLY",
        "MIGRATIONS_APPLIED=0",
        "DATABASE_RECORD_RECONCILIATION=BLOCKED_RUNTIME_EVIDENCE",
        f"API_ENDPOINTS_IMPLEMENTED={implemented_routes}_SOURCE_IMPLEMENTATIONS_OF_{len(endpoints['endpoints'])}_INVENTORIED_ROUTES",
        "OPENAPI_STATUS=BLOCKED_COMPLETE_GENERATED_SPEC_AND_RUNTIME_CONFORMANCE_REQUIRED",
        f"TESTS_PASSED={source_tests}_SOURCE_GATES_ONLY",
        "TESTS_FAILED=UNKNOWN_UNTIL_WORKFLOWS_COMPLETE",
        "SCREEN_POP_P95=BLOCKED_RUNTIME_EVIDENCE",
        "EVENT_PROCESSING_P95=BLOCKED_RUNTIME_EVIDENCE",
        "LOAD_TEST=BLOCKED_ISOLATED_STAGING_REQUIRED",
        "SECURITY_SCAN=BLOCKED_COMPLETE_RUNTIME_AND_DEPENDENCY_EVIDENCE_REQUIRED",
        "SECRET_SCAN=BLOCKED_WORKFLOW_EVIDENCE_REQUIRED",
        "SBOM_STATUS=SOURCE_ADDON_SBOM_ONLY_COMPLETE_IMAGE_SBOM_BLOCKED",
        "PROVENANCE_STATUS=BLOCKED",
        "BACKUP_EVIDENCE=BLOCKED",
        "RESTORE_EVIDENCE=BLOCKED",
        "STAGING_EVIDENCE=BLOCKED",
        "CANARY_EVIDENCE=BLOCKED",
        "ONE_HOUR_SOAK=BLOCKED",
        "ONE_BUSINESS_DAY_SOAK=BLOCKED",
        "ACTIVATED_CAMPAIGNS=0",
        "ACTIVATED_CHANNELS=NONE",
        "DISABLED_CHANNELS=EMAIL,SMS,CALLBACKS,N8N,LIVE_CALL_CONTROL,PSTN",
        "ROLLBACK_STATUS=BLOCKED_REHEARSAL_NOT_RUN",
        "PRODUCTION_STATUS=NOT_DEPLOYED",
        "FINAL_STATUS=BLOCKED",
        "BLOCKERS=" + " | ".join(blockers),
        "NEXT_SAFE_ACTION=COMPLETE_STACKED_PR_REVIEW_AND_EXACT_HEAD_CI_BEFORE_ISOLATED_STAGING",
    ]
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"RELEASE_REPORT_PATH={output.relative_to(ROOT)}")
    print("RELEASE_REPORT_FINAL_STATUS=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
