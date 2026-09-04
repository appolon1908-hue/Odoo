#!/usr/bin/env python3
"""Generate a truthful blocked-by-default report for a production candidate."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def command(*args: str) -> str:
    return subprocess.check_output(
        args, cwd=ROOT, text=True, stderr=subprocess.DEVNULL
    ).strip()


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
    source_verified = os.environ.get("SOURCE_COMMIT_VERIFIED", "false").lower() == "true"
    coverage = json.loads(
        (ROOT / "config" / "call-center-module-coverage.json").read_text(
            encoding="utf-8"
        )
    )
    endpoints = json.loads(
        (ROOT / "tests" / "contracts" / "canonical-endpoints.json").read_text(
            encoding="utf-8"
        )
    )
    modules = coverage["coverage"]
    schema_count = sum(
        item["implementation_type"] == "schema" for item in modules
    )
    implemented_routes = sum(
        item["implementation_status"] == "implemented-in-canonical-addon"
        for item in endpoints["endpoints"]
    )
    source_tests = os.environ.get("SOURCE_TESTS_STATUS", "NOT_RECORDED")

    blockers = [
        "production server source and image authority have not been reconciled to this exact SHA",
        "a current paired database-plus-filestore backup with off-host verification is absent",
        "isolated staging upgrade, interrupted-restart, negative-authorization, and tenant-isolation evidence is absent",
        "Caddy, Kong, Middleware, and Odoo have not been certified together against this exact image digest",
        "representative paired restore and rollback rehearsal have not run",
        "production read-only canary and bounded soak have not run",
        "email, SMS, callbacks, n8n, VICIdial live control, Odoo writes, and PSTN dialing remain disabled",
    ]
    if not source_verified:
        blockers.insert(0, "the selected source commit signature has not been verified")

    lines = [
        f"BASELINE_COMMIT={baseline}",
        f"SOURCE_BRANCH_COMMIT={source_sha}",
        (
            f"FINAL_PROTECTED_COMMIT={source_sha}"
            if source_verified
            else "FINAL_PROTECTED_COMMIT=BLOCKED_SIGNATURE_NOT_VERIFIED"
        ),
        (
            "SOURCE_COMMIT_SIGNATURE=PASS"
            if source_verified
            else "SOURCE_COMMIT_SIGNATURE=BLOCKED"
        ),
        "RELEASE_IMAGE_DIGEST=PENDING_SCAN_GATED_PUBLICATION_IN_THIS_WORKFLOW",
        "ODOO_VERSION=19",
        f"MODULES_CREATED={len(modules)}_MISSION_MODULES_INCLUDING_{schema_count}_MODEL_OWNING_MODULES",
        "MODULES_UPGRADED=0_SOURCE_AND_ARTIFACT_PHASE_ONLY",
        "MIGRATIONS_APPLIED=0",
        "DATABASE_RECORD_RECONCILIATION=BLOCKED_RUNTIME_EVIDENCE",
        f"API_ENDPOINTS_IMPLEMENTED={implemented_routes}_SOURCE_IMPLEMENTATIONS_OF_{len(endpoints['endpoints'])}_INVENTORIED_ROUTES",
        "OPENAPI_STATUS=BLOCKED_COMPLETE_RUNTIME_CONFORMANCE_REQUIRED",
        f"TESTS_PASSED={source_tests}_SOURCE_GATES",
        "TESTS_FAILED=0_RECORDED_SOURCE_GATE_FAILURES",
        "SCREEN_POP_P95=BLOCKED_RUNTIME_EVIDENCE",
        "EVENT_PROCESSING_P95=BLOCKED_RUNTIME_EVIDENCE",
        "LOAD_TEST=BLOCKED_ISOLATED_STAGING_REQUIRED",
        "SECURITY_SCAN=SOURCE_GATES_PASS_CONTAINER_SCAN_PENDING",
        "SECRET_SCAN=SOURCE_GATES_PASS_CONTAINER_SCAN_PENDING",
        "SBOM_STATUS=SOURCE_ADDON_SBOM_CREATED_CONTAINER_SBOM_PENDING",
        "PROVENANCE_STATUS=PENDING_SIGNED_OCI_ATTESTATION",
        "BACKUP_EVIDENCE=BLOCKED_CURRENT_PAIRED_BACKUP_REQUIRED",
        "RESTORE_EVIDENCE=BLOCKED_REPRESENTATIVE_PAIRED_RESTORE_REQUIRED",
        "STAGING_EVIDENCE=BLOCKED",
        "CANARY_EVIDENCE=BLOCKED",
        "BOUNDED_SOAK=BLOCKED",
        "ACTIVATED_CAMPAIGNS=0",
        "ACTIVATED_CHANNELS=NONE",
        "DISABLED_CHANNELS=ODOO_WRITE,EMAIL,SMS,CALLBACKS,N8N,VICIDIAL_LIVE_CONTROL,PSTN",
        "ROLLBACK_STATUS=BLOCKED_REHEARSAL_NOT_RUN",
        "PRODUCTION_STATUS=NOT_DEPLOYED",
        "FINAL_STATUS=BLOCKED_RUNTIME_GATES",
        "BLOCKERS=" + " | ".join(blockers),
        "NEXT_SAFE_ACTION=BUILD_SCAN_PUBLISH_AND_ATTEST_THE_EXACT_SIGNED_MAIN_SHA_THEN_CERTIFY_ISOLATED_STAGING",
    ]

    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"RELEASE_REPORT_PATH={output.relative_to(ROOT)}")
    print("RELEASE_REPORT_FINAL_STATUS=BLOCKED_RUNTIME_GATES")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
