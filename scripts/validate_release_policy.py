#!/usr/bin/env python3
"""Fail closed when the Odoo production release contract is weakened."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "release-policy.json"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "cc-release-candidate.yml"
CONTAINER_CI = ROOT / ".github" / "workflows" / "production-container-ci.yml"
DOCKERFILE = ROOT / "deploy" / "container" / "Dockerfile"
STAGING_ENV = ROOT / "deploy" / "environments" / "staging.env.example"
CANARY_ENV = (
    ROOT / "deploy" / "environments" / "production-readonly-canary.env.example"
)
EVIDENCE_TEMPLATE = ROOT / "release" / "production-evidence-template.json"
GITHUB_ACTION = re.compile(
    r"uses:\s+actions/[A-Za-z0-9_.-]+@[0-9a-f]{40}(?:\s+#.*)?$"
)
EXPECTED_IMAGE = "ghcr.io/appolon1908-hue/odoo"
EXPECTED_BASE = (
    "docker.io/library/odoo@"
    "sha256:f54272f31d5f77e4146b887efb3761c98480317daf687e4b4b5e76ed8bcc08c5"
)
TRIVY_VERSION_LINE = 'TRIVY_VERSION: "0.74.0"'
TRIVY_SHA_LINE = (
    'TRIVY_ARCHIVE_SHA256: '
    '"41839546f49977c0a26f86d83b0debb6d0d7bfa62b02092a136cd02bec86080d"'
)
EXPECTED_FLAGS = {
    "LIVE_ODOO_WRITE",
    "ENABLE_EXTERNAL_DELIVERY",
    "EMAIL_DELIVERY",
    "SMS_DELIVERY",
    "CALLBACK_DISPATCH",
    "PSTN_DIALING",
    "N8N_ACTIVATION",
    "VICIDIAL_LIVE_CONTROL",
}
EXPECTED_SOURCE_GATES = {
    "signed-protected-main-commit",
    "exact-main-source-validation",
    "merge-result-validation",
    "odoo-postgresql-runtime-tests",
    "production-container-build",
    "immutable-container-image-digest",
    "container-secret-scan",
    "fixed-critical-vulnerability-gate",
    "complete-container-spdx-sbom",
    "signed-slsa-provenance",
    "signed-sbom-attestation",
}
EXPECTED_RUNTIME_GATES = {
    "production-source-authority-reconciliation",
    "current-paired-database-filestore-backup",
    "off-host-backup-copy",
    "isolated-staging-upgrade-and-restart",
    "caddy-kong-middleware-odoo-contract-certification",
    "negative-authorization-and-tenant-isolation",
    "representative-database-filestore-restore",
    "rollback-rehearsal",
    "production-read-only-canary",
    "bounded-production-soak",
    "production-activation-approval",
}


def load_json(path: Path, errors: list[str]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"cannot load {path.relative_to(ROOT)}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{path.relative_to(ROOT)} must contain a JSON object")
        return {}
    return value


def string_set(value: Any, name: str, errors: list[str]) -> set[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        errors.append(f"{name} must be a non-empty string array")
        return set()
    if len(value) != len(set(value)):
        errors.append(f"{name} contains duplicates")
    return set(value)


def github_owned_pinned_actions(text: str, name: str, errors: list[str]) -> None:
    action_lines = [
        line.strip() for line in text.splitlines() if line.strip().startswith("uses:")
    ]
    if not action_lines:
        errors.append(f"{name} contains no actions")
    for line in action_lines:
        if not GITHUB_ACTION.fullmatch(line):
            errors.append(
                f"{name} action must be GitHub-owned and commit-pinned: {line}"
            )


def require_closed_flags(path: Path, errors: list[str]) -> None:
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    for flag in EXPECTED_FLAGS:
        if f"{flag}=false" not in text:
            errors.append(f"{path.relative_to(ROOT)} is missing {flag}=false")
    if re.search(
        r"(?i)(?:password|secret|token|private_key)\s*=\s*(?!REQUIRED_AT_RUNTIME$)\S+",
        text,
        re.MULTILINE,
    ):
        errors.append(f"{path.relative_to(ROOT)} contains a credential value")


def validate_policy(policy: dict[str, Any], errors: list[str]) -> None:
    exact = {
        "schema_version": 2,
        "release_type": "signed-oci-production-candidate",
        "workflow_dispatch_only": True,
        "automatic_publish": False,
        "automatic_deploy": False,
        "runtime_environment_changes": False,
        "artifact_publish_requires_exact_signed_main": True,
        "artifact_signing_required": True,
        "artifact_signing_mode": "github-actions-oidc-sigstore",
    }
    for key, expected in exact.items():
        if policy.get(key) != expected:
            errors.append(f"release policy {key} must be exactly {expected!r}")

    image = policy.get("immutable_image")
    if not isinstance(image, dict):
        errors.append("immutable_image must be an object")
    else:
        if image.get("name") != EXPECTED_IMAGE:
            errors.append(f"immutable_image.name must be {EXPECTED_IMAGE}")
        if image.get("tag_template") != "sha-{source_sha}":
            errors.append("immutable_image.tag_template must be sha-{source_sha}")
        if image.get("platform") != "linux/amd64":
            errors.append("immutable_image.platform must be linux/amd64")
        if image.get("base_image") != EXPECTED_BASE:
            errors.append("immutable_image.base_image must be the reviewed digest")

    if string_set(
        policy.get("required_source_gates"), "required_source_gates", errors
    ) != EXPECTED_SOURCE_GATES:
        errors.append("required_source_gates do not match the production contract")
    if string_set(
        policy.get("required_runtime_gates"), "required_runtime_gates", errors
    ) != EXPECTED_RUNTIME_GATES:
        errors.append("required_runtime_gates do not match the production contract")
    if string_set(
        policy.get("governed_runtime_flags"), "governed_runtime_flags", errors
    ) != EXPECTED_FLAGS:
        errors.append("governed_runtime_flags do not match the fail-closed contract")

    candidates = string_set(
        policy.get("candidate_artifacts"), "candidate_artifacts", errors
    )
    for required in (
        "immutable OCI image digest",
        "complete container SPDX SBOM",
        "signed SLSA provenance attestation",
        "signed SBOM attestation",
        "production candidate manifest",
    ):
        if required not in candidates:
            errors.append(f"candidate_artifacts is missing {required!r}")


def validate_scanner_install(text: str, name: str, errors: list[str]) -> None:
    for required in (
        TRIVY_VERSION_LINE,
        TRIVY_SHA_LINE,
        "Install checksum-verified Trivy",
        "sha256sum --check --strict",
        "aquasecurity/trivy/releases/download/v${TRIVY_VERSION}",
        "trivy image",
    ):
        if required not in text:
            errors.append(f"{name} is missing scanner control {required!r}")


def validate_release_workflow(errors: list[str]) -> None:
    text = (
        RELEASE_WORKFLOW.read_text(encoding="utf-8")
        if RELEASE_WORKFLOW.is_file()
        else ""
    )
    required = (
        "workflow_dispatch:",
        "expected_source_sha:",
        "BUILD_SIGNED_PRODUCTION_CANDIDATE",
        "contents: read",
        "packages: write",
        "id-token: write",
        "attestations: write",
        "artifact-metadata: write",
        "environment: odoo-production-candidate",
        'test "${{ github.ref_name }}" = "main"',
        "persist-credentials: false",
        "bash scripts/run_ci.sh",
        "bash scripts/build_release_candidate.sh",
        "docker login ghcr.io",
        "docker manifest inspect \"$IMAGE_TAG\"",
        "docker build \\",
        "Block fixed critical vulnerabilities",
        "Block secrets embedded in the image",
        "Publish immutable SHA tag and resolve registry digest",
        "docker push \"$IMAGE_TAG\"",
        "actions/attest-build-provenance@4d101475d8b20a2381f78447822ac1eab6504dd8",
        "actions/attest-sbom@c604332985a26aa8cf1bdc465b92731239ec6b9e",
        "subject-name:",
        "subject-digest:",
        "sbom-path:",
        "push-to-registry: true",
        "scripts/generate_container_release_manifest.py",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
        "PRODUCTION_DEPLOYED=NO",
        "LIVE_ODOO_WRITE=false",
        "PSTN_DIALING=false",
    )
    for item in required:
        if item not in text:
            errors.append(f"release workflow is missing {item!r}")
    validate_scanner_install(text, RELEASE_WORKFLOW.name, errors)

    lowered = text.lower()
    for forbidden in (
        "pull_request:\n",
        "schedule:\n",
        "ssh ",
        "rsync ",
        "kubectl ",
        "docker compose ",
        "pg_restore",
        "psql ",
        "odoo-bin",
        "--update=",
        "--init=",
        ":latest",
        "git push",
        "gh release",
    ):
        if forbidden in lowered:
            errors.append(
                f"release workflow contains prohibited operation {forbidden.strip()!r}"
            )

    scan_position = text.find("Block fixed critical vulnerabilities")
    publish_position = text.find(
        "Publish immutable SHA tag and resolve registry digest"
    )
    if scan_position < 0 or publish_position < 0 or scan_position > publish_position:
        errors.append("container publication must occur only after the critical gate")
    github_owned_pinned_actions(text, RELEASE_WORKFLOW.name, errors)


def validate_container_ci(errors: list[str]) -> None:
    text = CONTAINER_CI.read_text(encoding="utf-8") if CONTAINER_CI.is_file() else ""
    for required in (
        "permissions:\n  contents: read",
        "persist-credentials: false",
        "docker build \\",
        "deploy/container/Dockerfile",
        "Block fixed critical vulnerabilities",
        "Block secrets embedded in the image",
        "Generate container SPDX SBOM",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
    ):
        if required not in text:
            errors.append(f"production container CI is missing {required!r}")
    validate_scanner_install(text, CONTAINER_CI.name, errors)

    lowered = text.lower()
    for forbidden in (
        "packages: write",
        "id-token: write",
        "docker login",
        "docker push",
        "push: true",
        "ssh ",
        "rsync ",
        "kubectl ",
        ":latest",
    ):
        if forbidden in lowered:
            errors.append(
                f"production container CI contains prohibited {forbidden!r}"
            )
    github_owned_pinned_actions(text, CONTAINER_CI.name, errors)


def validate_dockerfile(errors: list[str]) -> None:
    text = DOCKERFILE.read_text(encoding="utf-8") if DOCKERFILE.is_file() else ""
    if f"FROM {EXPECTED_BASE}" not in text:
        errors.append("production Dockerfile must use the reviewed Odoo digest")
    for required in (
        "COPY --chown=odoo:odoo custom-addons/ /mnt/extra-addons/",
        "find /mnt/extra-addons -type l",
        "USER odoo",
    ):
        if required not in text:
            errors.append(f"production Dockerfile is missing {required!r}")
    for forbidden in (
        "apt-get",
        "apk add",
        "pip install",
        "curl ",
        "wget ",
        " git clone",
        ":latest",
    ):
        if forbidden in text.lower():
            errors.append(f"production Dockerfile contains prohibited {forbidden!r}")


def validate_evidence_template(errors: list[str]) -> None:
    document = load_json(EVIDENCE_TEMPLATE, errors)
    if document.get("schema_version") != 1:
        errors.append("production evidence template schema_version must be 1")
    if document.get("verdict") != "BLOCKED":
        errors.append("production evidence template must default to BLOCKED")
    if document.get("source_sha") != "0" * 40:
        errors.append("production evidence template source_sha must be unset")
    image = document.get("image")
    if not isinstance(image, dict) or image.get("digest") != "sha256:" + "0" * 64:
        errors.append("production evidence template image digest must be unset")
    flags = document.get("runtime_flags")
    if not isinstance(flags, dict) or set(flags) != EXPECTED_FLAGS:
        errors.append("production evidence template flags do not match policy")
    elif any(value is not False for value in flags.values()):
        errors.append("production evidence template must default every live flag false")


def main() -> int:
    errors: list[str] = []
    policy = load_json(POLICY, errors)
    validate_policy(policy, errors)
    validate_release_workflow(errors)
    validate_container_ci(errors)
    validate_dockerfile(errors)
    require_closed_flags(STAGING_ENV, errors)
    require_closed_flags(CANARY_ENV, errors)
    validate_evidence_template(errors)

    if errors:
        print("Release policy validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("RELEASE_WORKFLOW_DISPATCH_ONLY=PASS")
    print("RELEASE_SOURCE_IDENTITY=SIGNED_MAIN_ONLY")
    print("RELEASE_ACTIONS=GITHUB_OWNED_AND_COMMIT_PINNED")
    print("TRIVY_BINARY=VERSION_AND_SHA256_PINNED")
    print("PRODUCTION_IMAGE_BASE=DIGEST_PINNED")
    print("PRODUCTION_IMAGE_PUBLICATION=SCAN_GATED")
    print("PRODUCTION_ATTESTATIONS=SIGSTORE_REQUIRED")
    print("AUTOMATIC_DEPLOY=DISABLED")
    print("STAGING_AND_CANARY_LIVE_CAPABILITIES=CLOSED")
    print("PRODUCTION_EVIDENCE_DEFAULT=BLOCKED")
    print("RELEASE_POLICY_SOURCE_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
