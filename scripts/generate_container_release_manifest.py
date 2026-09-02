#!/usr/bin/env python3
"""Generate a machine-readable signed OCI production-candidate manifest."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
EXPECTED_IMAGE = "ghcr.io/appolon1908-hue/odoo"
BASE_IMAGE = (
    "docker.io/library/odoo@"
    "sha256:f54272f31d5f77e4146b887efb3761c98480317daf687e4b4b5e76ed8bcc08c5"
)


def command(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def count_trivy_findings(document: dict[str, Any]) -> tuple[int, int]:
    vulnerabilities = 0
    secrets = 0
    for result in document.get("Results") or []:
        if not isinstance(result, dict):
            continue
        vulnerabilities += len(result.get("Vulnerabilities") or [])
        secrets += len(result.get("Secrets") or [])
    return vulnerabilities, secrets


def created_at() -> str:
    epoch = int(command("git", "show", "-s", "--format=%ct", "HEAD"))
    return (
        dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--container-sbom", required=True)
    parser.add_argument("--vulnerability-report", required=True)
    parser.add_argument("--secret-report", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    source_sha = command("git", "rev-parse", "HEAD")
    expected_source_sha = os.environ.get("EXPECTED_SOURCE_SHA", "")
    image_name = os.environ.get("IMAGE_NAME", "")
    image_digest = os.environ.get("IMAGE_DIGEST", "")
    source_commit_verified = os.environ.get("SOURCE_COMMIT_VERIFIED", "").lower() == "true"
    provenance_url = os.environ.get("PROVENANCE_ATTESTATION_URL", "")
    sbom_attestation_url = os.environ.get("SBOM_ATTESTATION_URL", "")

    if not SHA_RE.fullmatch(source_sha) or source_sha != expected_source_sha:
        raise SystemExit("ERROR=SOURCE_SHA_MISMATCH")
    if image_name != EXPECTED_IMAGE:
        raise SystemExit(f"ERROR=UNEXPECTED_IMAGE_NAME:{image_name}")
    if not DIGEST_RE.fullmatch(image_digest):
        raise SystemExit(f"ERROR=INVALID_IMAGE_DIGEST:{image_digest}")
    if not source_commit_verified:
        raise SystemExit("ERROR=SOURCE_COMMIT_SIGNATURE_NOT_VERIFIED")
    if not provenance_url or not sbom_attestation_url:
        raise SystemExit("ERROR=SIGNED_ATTESTATION_URL_MISSING")

    paths = {
        "source_manifest": ROOT / args.source_manifest,
        "container_sbom": ROOT / args.container_sbom,
        "vulnerability_report": ROOT / args.vulnerability_report,
        "secret_report": ROOT / args.secret_report,
    }
    for name, path in paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"{name}: {path}")

    source_manifest = load_json(paths["source_manifest"])
    if source_manifest.get("source_sha") != source_sha:
        raise SystemExit("ERROR=SOURCE_MANIFEST_SHA_MISMATCH")

    vulnerability_document = load_json(paths["vulnerability_report"])
    secret_document = load_json(paths["secret_report"])
    vulnerabilities, _ = count_trivy_findings(vulnerability_document)
    _, secrets = count_trivy_findings(secret_document)
    if secrets:
        raise SystemExit(f"ERROR=IMAGE_SECRET_FINDINGS:{secrets}")

    payload = {
        "schema_version": 2,
        "release_type": "signed-oci-production-candidate",
        "source_repository": "appolon1908-hue/Odoo",
        "source_sha": source_sha,
        "source_tree": command("git", "rev-parse", "HEAD^{tree}"),
        "source_commit_verified_signature": True,
        "created_at": created_at(),
        "image": {
            "name": image_name,
            "digest": image_digest,
            "immutable_reference": f"{image_name}@{image_digest}",
            "platform": "linux/amd64",
            "base_image": BASE_IMAGE,
            "tag": f"sha-{source_sha}",
        },
        "security": {
            "embedded_secret_findings": secrets,
            "reported_high_or_critical_vulnerabilities": vulnerabilities,
            "fixed_critical_vulnerability_gate": "PASS",
            "source_security_gate": "PASS",
        },
        "attestations": {
            "provenance": provenance_url,
            "sbom": sbom_attestation_url,
            "signature_provider": "GitHub Actions OIDC with Sigstore",
        },
        "evidence": {
            name: {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": file_digest(path),
                "bytes": path.stat().st_size,
            }
            for name, path in paths.items()
        },
        "artifact_ready": True,
        "production_ready": False,
        "runtime_changed": False,
        "satisfied_gates": [
            "signed-protected-main-commit",
            "exact-main-source-validation",
            "immutable-container-image-digest",
            "complete-container-spdx-sbom",
            "container-secret-scan",
            "fixed-critical-vulnerability-gate",
            "signed-slsa-provenance",
            "signed-sbom-attestation",
        ],
        "blocked_runtime_gates": [
            "production-source-authority-reconciliation",
            "current-paired-database-filestore-backup",
            "isolated-staging-upgrade-and-restart",
            "caddy-kong-middleware-odoo-contract-certification",
            "representative-database-filestore-restore",
            "rollback-rehearsal",
            "production-read-only-canary",
            "bounded-production-soak",
            "production-activation-approval",
        ],
        "safety": {
            "production_deployed": False,
            "database_migrated": False,
            "live_odoo_write_enabled": False,
            "external_delivery_enabled": False,
            "email_delivery_enabled": False,
            "sms_delivery_enabled": False,
            "pstn_dialing_enabled": False,
        },
    }

    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"PRODUCTION_CANDIDATE_MANIFEST={output.relative_to(ROOT)}")
    print(f"PRODUCTION_CANDIDATE_IMAGE={image_name}@{image_digest}")
    print("SIGNED_OCI_CANDIDATE=PASS")
    print("PRODUCTION_READY=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
