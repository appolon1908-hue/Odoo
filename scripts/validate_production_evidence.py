#!/usr/bin/env python3
"""Validate sanitized Odoo staging and production certification evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
HEX_RE = re.compile(r"^[0-9a-f]{64}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
ZERO_SHA = "0" * 40
ZERO_DIGEST = "sha256:" + "0" * 64
EXPECTED_IMAGE = "ghcr.io/appolon1908-hue/odoo"
EXPECTED_REPOSITORY = "appolon1908-hue/Odoo"
EXPECTED_WORKFLOW = f"{EXPECTED_REPOSITORY}/.github/workflows/cc-release-candidate.yml"
PREDICATE_TYPES = {
    "provenance": "https://slsa.dev/provenance/v1",
    "sbom": "https://spdx.dev/Document",
}
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


def require_true(
    mapping: dict[str, Any], keys: tuple[str, ...], prefix: str, errors: list[str]
) -> None:
    for key in keys:
        if mapping.get(key) is not True:
            errors.append(f"{prefix}.{key} must be true")


def require_nonnegative(
    mapping: dict[str, Any], key: str, prefix: str, errors: list[str]
) -> None:
    value = mapping.get(key)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or (isinstance(value, float) and not math.isfinite(value))
        or value < 0
    ):
        errors.append(f"{prefix}.{key} must be a non-negative number")


def require_positive(
    mapping: dict[str, Any], key: str, prefix: str, errors: list[str]
) -> None:
    value = mapping.get(key)
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or (isinstance(value, float) and not math.isfinite(value))
        or value <= 0
    ):
        errors.append(f"{prefix}.{key} must be a positive number")


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def load_json(path: Path, name: str, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(f"cannot load {name}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{name} must contain a JSON object")
        return {}
    return value


def repo_path(value: Any, name: str, errors: list[str]) -> Path | None:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        errors.append(f"{name} must be a non-empty repository-relative path")
        return None
    path = (ROOT / value).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError:
        errors.append(f"{name} escapes the repository")
        return None
    if not path.is_file():
        errors.append(f"{name} does not exist: {value}")
        return None
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_checksums(path: Path, errors: list[str]) -> dict[str, str]:
    entries: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        errors.append(f"cannot read candidate.checksums_path: {exc}")
        return entries
    for number, line in enumerate(lines, 1):
        match = re.fullmatch(r"([0-9a-f]{64}) [ *](.+)", line)
        if not match:
            errors.append(f"candidate checksum line {number} is invalid")
            continue
        digest, name = match.groups()
        if name in entries:
            errors.append(f"candidate checksum entry is duplicated: {name}")
            continue
        candidate = (path.parent / name).resolve()
        try:
            candidate.relative_to(path.parent.resolve())
            candidate.relative_to(ROOT)
        except ValueError:
            errors.append(f"candidate checksum path escapes its artifact directory: {name}")
            continue
        if not candidate.is_file():
            errors.append(f"candidate checksum target is missing: {name}")
            continue
        actual = sha256_file(candidate)
        if actual != digest:
            errors.append(f"candidate checksum mismatch: {name}")
            continue
        entries[name] = digest
    if not entries:
        errors.append("candidate checksum set is empty")
    return entries


def verify_attestation(
    path: Path, kind: str, source_sha: str, image_digest: str, errors: list[str]
) -> None:
    """Use GitHub's cryptographic verifier; JSON shape/flags are not trust roots.

    The bundle may be a single JSON bundle or JSONL, as emitted by GitHub.
    Credentials and verifier diagnostics must never be echoed into evidence.
    """
    command = [
        "gh", "attestation", "verify", f"oci://{EXPECTED_IMAGE}@{image_digest}",
        "--bundle", str(path),
        "--repo", EXPECTED_REPOSITORY,
        "--cert-oidc-issuer", "https://token.actions.githubusercontent.com",
        "--cert-identity", f"https://github.com/{EXPECTED_WORKFLOW}@refs/heads/main",
        "--signer-workflow", EXPECTED_WORKFLOW,
        "--signer-digest", source_sha,
        "--source-digest", source_sha,
        "--source-ref", "refs/heads/main",
        "--predicate-type", PREDICATE_TYPES[kind],
        "--deny-self-hosted-runners",
        "--format", "json",
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        errors.append(f"candidate.{kind} cryptographic verifier unavailable or timed out")
        return
    if result.returncode != 0:
        errors.append(f"candidate.{kind} cryptographic attestation verification failed")
        return
    try:
        verified = json.loads(
            result.stdout, object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except ValueError:
        verified = None
    if (
        not isinstance(verified, list) or not verified
        or not all(isinstance(item, dict) and item.get("verificationResult") for item in verified)
    ):
        errors.append(f"candidate.{kind} verifier returned no verified attestations")


def validate_candidate_binding(
    document: dict[str, Any],
    source_sha: str,
    image_digest: str,
    errors: list[str],
) -> None:
    candidate = require_mapping(document.get("candidate"), "candidate", errors)
    manifest_path = repo_path(candidate.get("manifest_path"), "candidate.manifest_path", errors)
    checksums_path = repo_path(
        candidate.get("checksums_path"), "candidate.checksums_path", errors
    )
    provenance_path = repo_path(
        candidate.get("provenance_bundle_path"),
        "candidate.provenance_bundle_path",
        errors,
    )
    sbom_path = repo_path(
        candidate.get("sbom_bundle_path"), "candidate.sbom_bundle_path", errors
    )
    if candidate.get("provenance_verified") is not True:
        errors.append("candidate.provenance_verified must be true")
    if candidate.get("sbom_verified") is not True:
        errors.append("candidate.sbom_verified must be true")

    if None in (manifest_path, checksums_path, provenance_path, sbom_path):
        return
    assert manifest_path is not None
    assert checksums_path is not None
    assert provenance_path is not None
    assert sbom_path is not None

    checksums = load_checksums(checksums_path, errors)
    for artifact, label in (
        (manifest_path, "production candidate manifest"),
        (provenance_path, "provenance bundle"),
        (sbom_path, "SBOM bundle"),
    ):
        try:
            relative = artifact.relative_to(checksums_path.parent).as_posix()
        except ValueError:
            errors.append(f"{label} must be inside the checksum artifact directory")
            continue
        if checksums.get(relative) != sha256_file(artifact):
            errors.append(f"{label} is not bound by the candidate checksum set")

    manifest = load_json(manifest_path, "candidate manifest", errors)
    if manifest.get("schema_version") != 2:
        errors.append("candidate manifest schema_version must be 2")
    if manifest.get("release_type") != "signed-oci-production-candidate":
        errors.append("candidate manifest release_type is invalid")
    if manifest.get("source_repository") != EXPECTED_REPOSITORY:
        errors.append(f"candidate manifest source_repository must be {EXPECTED_REPOSITORY}")
    if manifest.get("source_sha") != source_sha:
        errors.append("candidate manifest source_sha does not match evidence")
    if manifest.get("source_commit_verified_signature") is not True:
        errors.append("candidate manifest must record a verified source signature")
    if manifest.get("artifact_ready") is not True:
        errors.append("candidate manifest artifact_ready must be true")
    image = require_mapping(manifest.get("image"), "candidate manifest image", errors)
    if image.get("name") != EXPECTED_IMAGE:
        errors.append("candidate manifest image name does not match")
    if image.get("digest") != image_digest:
        errors.append("candidate manifest image digest does not match evidence")
    attestations = require_mapping(
        manifest.get("attestations"), "candidate manifest attestations", errors
    )
    for key in ("provenance", "sbom"):
        value = attestations.get(key)
        if not isinstance(value, str) or not value.startswith("https://"):
            errors.append(f"candidate manifest attestations.{key} must be an HTTPS URL")
    safety = require_mapping(manifest.get("safety"), "candidate manifest safety", errors)
    for key in (
        "production_deployed",
        "database_migrated",
        "live_odoo_write_enabled",
        "external_delivery_enabled",
        "email_delivery_enabled",
        "sms_delivery_enabled",
        "pstn_dialing_enabled",
    ):
        if safety.get(key) is not False:
            errors.append(f"candidate manifest safety.{key} must be false")

    # Reject malformed local evidence before any registry/network operation.
    if not errors:
        verify_attestation(provenance_path, "provenance", source_sha, image_digest, errors)
        verify_attestation(sbom_path, "sbom", source_sha, image_digest, errors)


def validate_activation_approval(
    document: dict[str, Any],
    source_sha: str,
    image_digest: str,
    errors: list[str],
) -> None:
    approval = require_mapping(
        document.get("activation_approval"), "activation_approval", errors
    )
    if approval.get("approved") is not True:
        errors.append("activation_approval.approved must be true")
    approver = approval.get("approver")
    author = approval.get("candidate_author")
    if not isinstance(approver, str) or not approver.strip():
        errors.append("activation_approval.approver must be recorded")
    if not isinstance(author, str) or not author.strip():
        errors.append("activation_approval.candidate_author must be recorded")
    if (
        isinstance(approver, str) and isinstance(author, str)
        and approver.strip().casefold() == author.strip().casefold()
    ):
        errors.append("activation approval must be independent of the candidate author")
    if approval.get("review_state") != "APPROVED":
        errors.append("activation_approval.review_state must be APPROVED")
    if approval.get("source_sha") != source_sha:
        errors.append("activation_approval.source_sha must match the certified source")
    if approval.get("image_digest") != image_digest:
        errors.append(
            "activation_approval.image_digest must match the certified image"
        )
    review_url = approval.get("review_url")
    if (
        not isinstance(review_url, str)
        or not review_url.startswith("https://github.com/")
        or "/pull/" not in review_url
    ):
        errors.append("activation_approval.review_url must identify a GitHub PR review")
    approved_at = approval.get("approved_at")
    if not isinstance(approved_at, str) or not UTC_RE.fullmatch(approved_at):
        errors.append("activation_approval.approved_at must be an exact UTC timestamp")
    if approval.get("provenance") != "github-protected-review":
        errors.append(
            "activation_approval.provenance must be github-protected-review"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True)
    parser.add_argument(
        "--allow-blocked-template",
        action="store_true",
        help="Allow zeroed identifiers only for the committed BLOCKED template.",
    )
    args = parser.parse_args(argv)

    path = (ROOT / args.file).resolve()
    try:
        path.relative_to(ROOT)
    except ValueError:
        print("ERROR=evidence path escapes repository", file=sys.stderr)
        return 1

    errors: list[str] = []
    document = load_json(path, "evidence", errors)
    if not document:
        for error in errors:
            print(f"ERROR={error}", file=sys.stderr)
        return 1

    if document.get("schema_version") != 1:
        errors.append("schema_version must be 1")

    verdict = document.get("verdict")
    if not isinstance(verdict, str) or verdict not in VERDICTS:
        errors.append("verdict is invalid")
    source_sha = document.get("source_sha")
    image = require_mapping(document.get("image"), "image", errors)
    image_digest = image.get("digest")
    blocked_template = (
        args.allow_blocked_template
        and verdict == "BLOCKED"
        and source_sha == ZERO_SHA
        and image_digest == ZERO_DIGEST
    )

    if not blocked_template:
        if (
            not isinstance(source_sha, str)
            or not SHA_RE.fullmatch(source_sha)
            or source_sha == ZERO_SHA
        ):
            errors.append(
                "source_sha must be a non-zero 40-character lowercase Git SHA"
            )
        if (
            not isinstance(image_digest, str)
            or not DIGEST_RE.fullmatch(image_digest)
            or image_digest == ZERO_DIGEST
        ):
            errors.append("image.digest must be a non-zero sha256 OCI digest")
    if image.get("name") != EXPECTED_IMAGE:
        errors.append(f"image.name must be {EXPECTED_IMAGE}")

    environment = document.get("environment")
    if not isinstance(environment, str) or environment not in {
        "staging", "production-read-only-canary", "production"
    }:
        errors.append("environment is not supported")

    flags = require_mapping(document.get("runtime_flags"), "runtime_flags", errors)
    if set(flags) != REQUIRED_FLAGS:
        errors.append("runtime_flags must contain exactly the governed release flags")
    for key, value in flags.items():
        if not isinstance(value, bool):
            errors.append(f"runtime_flags.{key} must be boolean")

    approved = document.get("approved_live_capabilities")
    if not isinstance(approved, list) or not all(
        isinstance(item, str) and item in REQUIRED_FLAGS for item in approved
    ):
        errors.append(
            "approved_live_capabilities must be a list of governed flag names"
        )
        approved = []
    if len(approved) != len(set(approved)):
        errors.append("approved_live_capabilities contains duplicates")
    true_flags = {name for name, value in flags.items() if value is True}
    if true_flags != set(approved):
        errors.append(
            "approved_live_capabilities must exactly match true runtime flags"
        )

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

    if verdict != "BLOCKED":
        if isinstance(source_sha, str) and isinstance(image_digest, str):
            validate_candidate_binding(document, source_sha, image_digest, errors)
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
                "negative_authorization_passed",
            ),
            "integration",
            errors,
        )
        if type(integration.get("unexpected_external_effects")) is not int or integration.get("unexpected_external_effects") != 0:
            errors.append("integration.unexpected_external_effects must be 0")
        for digest_name in ("database_sha256", "filestore_sha256"):
            value = backup.get(digest_name)
            if not isinstance(value, str) or not HEX_RE.fullmatch(value) or value == "0" * 64:
                errors.append(f"backup.{digest_name} must be a non-zero SHA-256 digest")
        completed_at = backup.get("paired_backup_completed_at")
        try:
            if not isinstance(completed_at, str) or not UTC_RE.fullmatch(completed_at):
                raise ValueError
            datetime.strptime(completed_at, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            errors.append("backup.paired_backup_completed_at must be a valid UTC timestamp")
        if backup.get("off_host_copy_verified") is not True:
            errors.append("backup.off_host_copy_verified must be true")

    if isinstance(verdict, str) and verdict in {
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
        if type(canary.get("unexpected_writes")) is not int or canary.get("unexpected_writes") != 0:
            errors.append("canary.unexpected_writes must be 0")
        require_positive(canary, "duration_minutes", "canary", errors)
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
        if true_flags:
            errors.append("read-only canary requires every live-effect flag false")
    elif verdict == "PRODUCTION_CERTIFIED":
        if environment != "production":
            errors.append("PRODUCTION_CERTIFIED requires environment=production")
        if soak.get("passed") is not True:
            errors.append("soak.passed must be true")
        require_positive(soak, "duration_minutes", "soak", errors)
        require_nonnegative(soak, "error_rate", "soak", errors)
        require_nonnegative(soak, "reconciliation_backlog", "soak", errors)
        if isinstance(source_sha, str) and isinstance(image_digest, str):
            validate_activation_approval(document, source_sha, image_digest, errors)
    elif not args.allow_blocked_template:
        errors.append("BLOCKED evidence is not a production certification")
    elif not blocked_template:
        errors.append(
            "--allow-blocked-template accepts only the zero-identity BLOCKED template"
        )
    elif true_flags:
        errors.append("blocked template requires all live flags false")

    if errors:
        print("Production evidence validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"PRODUCTION_EVIDENCE_FILE={path.relative_to(ROOT)}")
    print(f"PRODUCTION_EVIDENCE_VERDICT={verdict}")
    print("SIGNED_CANDIDATE_BINDING=PASS" if verdict != "BLOCKED" else "SIGNED_CANDIDATE_BINDING=BLOCKED")
    print("PRODUCTION_EVIDENCE_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
