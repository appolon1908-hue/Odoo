#!/usr/bin/env python3
"""Validate sanitized Odoo staging and production certification evidence."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
HEX_RE = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_IMAGE = "ghcr.io/appolon1908-hue/odoo"
REQUIRED_FLAGS = {
    "LIVE_ODOO_WRITE",
    "ENABLE_EXTERNAL_DELIVERY",
    "EMAIL_DELIVERY",
    "SMS_DELIVERY",
    "CALLBACK_DISPATCH",
    "PSTN_DIALING",
    "N8N_ACTIVATION",
    "VICIDIAL_LIVE_CONTROL",
}
VERDICTS = {
    "BLOCKED",
    "STAGING_CERTIFIED",
    "PRODUCTION_READ_ONLY_CANARY_CERTIFIED",
    "PRODUCTION_CERTIFIED",
}


def require_mapping(value: Any, name: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{name} must be an object")
        return {}
    return value


def require_true(mapping: dict[str, Any], keys: tuple[str, ...], prefix: str, errors: list[str]) -> None:
    for key in keys:
        if mapping.get(key) is not True:
            errors.append(f"{prefix}.{key} must be true")


def require_nonnegative(mapping: dict[str, Any], key: str, prefix: str, errors: list[str]) -> None:
    value = mapping.get(key)
    if not isinstance(value, (int, float)) or value < 0:
        errors.append(f"{prefix}.{key} must be a non-negative number")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument(
        "--allow-blocked-template",
        action="store_true",
        help="Allow zeroed identifiers and a BLOCKED verdict for the committed template.",
    )
    args = parser.parse_args()

    path = (ROOT / args.file).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError:
        print("ERROR=evidence path escapes repository", file=sys.stderr)
        return 1

    errors: list[str] = []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR=cannot load evidence: {exc}", file=sys.stderr)
        return 1
    if not isinstance(document, dict):
        print("ERROR=evidence must be a JSON object", file=sys.stderr)
        return 1

    if document.get("schema_version") != 1:
        errors.append("schema_version must be 1")

    source_sha = document.get("source_sha")
    image = require_mapping(document.get("image"), "image", errors)
    image_digest = image.get("digest")
    zero_template = (
        args.allow_blocked_template
        and source_sha == "0" * 40
        and image_digest == "sha256:" + "0" * 64
    )
    if not zero_template and not (isinstance(source_sha, str) and SHA_RE.fullmatch(source_sha)):
        errors.append("source_sha must be a 40-character lowercase Git SHA")
    if image.get("name") != EXPECTED_IMAGE:
        errors.append(f"image.name must be {EXPECTED_IMAGE}")
    if not zero_template and not (
        isinstance(image_digest, str) and DIGEST_RE.fullmatch(image_digest)
    ):
        errors.append("image.digest must be a sha256 OCI digest")

    environment = document.get("environment")
    if environment not in {"staging", "production-read-only-canary", "production"}:
        errors.append("environment is not supported")

    flags = require_mapping(document.get("runtime_flags"), "runtime_flags", errors)
    if set(flags) != REQUIRED_FLAGS:
        errors.append("runtime_flags must contain exactly the governed release flags")
    for key, value in flags.items():
        if not isinstance(value, bool):
            errors.append(f"runtime_flags.{key} must be boolean")

    source_authority = require_mapping(
        document.get("source_authority"), "source_authority", errors
    )
    backup = require_mapping(document.get("backup"), "backup", errors)
    migration = require_mapping(document.get("migration"), "migration", errors)
    restore = require_mapping(document.get("restore"), "restore", errors)
    integration = require_mapping(document.get("integration"), "integration", errors)
    rollback = require_mapping(document.get("rollback"), "rollback", errors)
    canary = require_mapping(document.get("canary"), "canary", errors)
    soak = require_mapping(document.get("soak"), "soak", errors)

    approved = document.get("approved_live_capabilities")
    if not isinstance(approved, list) or not all(
        isinstance(item, str) and item in REQUIRED_FLAGS for item in approved
    ):
        errors.append("approved_live_capabilities must be a list of governed flag names")
        approved = []
    if len(approved) != len(set(approved)):
        errors.append("approved_live_capabilities contains duplicates")
    true_flags = {name for name, value in flags.items() if value is True}
    if true_flags != set(approved):
        errors.append("approved_live_capabilities must exactly match true runtime flags")

    verdict = document.get("verdict")
    if verdict not in VERDICTS:
        errors.append("verdict is invalid")

    if verdict != "BLOCKED":
        require_true(
            source_authority,
            (
                "server_matches_source_sha",
                "server_matches_image_digest",
                "mutable_host_checkout_removed",
            ),
            "source_authority",
            errors,
        )
        require_true(
            migration,
            ("upgrade_passed", "interrupted_restart_passed", "schema_audit_passed"),
            "migration",
            errors,
        )
        require_true(
            restore,
            ("database_restored", "filestore_restored", "checksums_verified"),
            "restore",
            errors,
        )
        require_nonnegative(restore, "rto_seconds", "restore", errors)
        require_true(
            integration,
            (
                "caddy_passed",
                "kong_passed",
                "middleware_passed",
                "odoo_passed",
                "idempotency_passed",
                "tenant_isolation_passed",
            ),
            "integration",
            errors,
        )
        if integration.get("unexpected_external_effects") != 0:
            errors.append("integration.unexpected_external_effects must be 0")

        for digest_name in ("database_sha256", "filestore_sha256"):
            value = backup.get(digest_name)
            if not isinstance(value, str) or not HEX_RE.fullmatch(value):
                errors.append(f"backup.{digest_name} must be a SHA-256 digest")
        if not isinstance(backup.get("paired_backup_completed_at"), str):
            errors.append("backup.paired_backup_completed_at must be recorded")
        if backup.get("off_host_copy_verified") is not True:
            errors.append("backup.off_host_copy_verified must be true")

    if verdict in {
        "PRODUCTION_READ_ONLY_CANARY_CERTIFIED",
        "PRODUCTION_CERTIFIED",
    }:
        require_true(
            rollback,
            (
                "rehearsed",
                "source_restored",
                "database_restored",
                "filestore_restored",
                "post_rollback_smoke_passed",
            ),
            "rollback",
            errors,
        )
        if canary.get("passed") is not True:
            errors.append("canary.passed must be true")
        if canary.get("unexpected_writes") != 0:
            errors.append("canary.unexpected_writes must be 0")
        require_nonnegative(canary, "duration_minutes", "canary", errors)
        require_nonnegative(canary, "error_rate", "canary", errors)

    if verdict == "STAGING_CERTIFIED":
        if environment != "staging":
            errors.append("STAGING_CERTIFIED requires environment=staging")
        if true_flags:
            errors.append("staging certification requires all live flags false")
    elif verdict == "PRODUCTION_READ_ONLY_CANARY_CERTIFIED":
        if environment != "production-read-only-canary":
            errors.append(
                "PRODUCTION_READ_ONLY_CANARY_CERTIFIED requires the read-only canary environment"
            )
        if flags.get("LIVE_ODOO_WRITE") is not False:
            errors.append("read-only canary requires LIVE_ODOO_WRITE=false")
    elif verdict == "PRODUCTION_CERTIFIED":
        if environment != "production":
            errors.append("PRODUCTION_CERTIFIED requires environment=production")
        if soak.get("passed") is not True:
            errors.append("soak.passed must be true")
        require_nonnegative(soak, "duration_minutes", "soak", errors)
        require_nonnegative(soak, "error_rate", "soak", errors)
        require_nonnegative(soak, "reconciliation_backlog", "soak", errors)
    elif not args.allow_blocked_template:
        errors.append("BLOCKED evidence is not a production certification")

    if errors:
        print("Production evidence validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"PRODUCTION_EVIDENCE_FILE={path.relative_to(ROOT)}")
    print(f"PRODUCTION_EVIDENCE_VERDICT={verdict}")
    print("PRODUCTION_EVIDENCE_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
