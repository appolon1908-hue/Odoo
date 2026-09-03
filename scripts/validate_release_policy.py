#!/usr/bin/env python3
"""Fail closed when the Odoo production release contract is weakened."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P = lambda *parts: ROOT.joinpath(*parts)
POLICY = P("config", "release-policy.json")
RELEASE = P(".github", "workflows", "cc-release-candidate.yml")
CONTAINER_CI = P(".github", "workflows", "production-container-ci.yml")
INSTALLER = P("scripts", "install_trivy.sh")
DOCKERFILE = P("deploy", "container", "Dockerfile")
STAGING = P("deploy", "environments", "staging.env.example")
CANARY = P("deploy", "environments", "production-readonly-canary.env.example")
TEMPLATE = P("release", "production-evidence-template.json")

IMAGE = "ghcr.io/appolon1908-hue/odoo"
BASE = "docker.io/library/odoo@sha256:f54272f31d5f77e4146b887efb3761c98480317daf687e4b4b5e76ed8bcc08c5"
TRIVY_VERSION = 'TRIVY_VERSION="0.74.0"'
TRIVY_SHA = 'TRIVY_ARCHIVE_SHA256="2ae6fe3ee734b7fdf11335663e18c75ea12dccc76062f09f164a3b0f8be4371a"'
FLAGS = {
    "LIVE_ODOO_WRITE", "ENABLE_EXTERNAL_DELIVERY", "EMAIL_DELIVERY",
    "SMS_DELIVERY", "CALLBACK_DISPATCH", "PSTN_DIALING",
    "N8N_ACTIVATION", "VICIDIAL_LIVE_CONTROL",
}
SOURCE_GATES = {
    "signed-protected-main-commit", "exact-main-source-validation",
    "merge-result-validation", "odoo-postgresql-runtime-tests",
    "production-container-build", "immutable-container-image-digest",
    "container-secret-scan", "fixed-critical-vulnerability-gate",
    "complete-container-spdx-sbom", "signed-slsa-provenance",
    "signed-sbom-attestation",
}
RUNTIME_GATES = {
    "production-source-authority-reconciliation",
    "current-paired-database-filestore-backup", "off-host-backup-copy",
    "isolated-staging-upgrade-and-restart",
    "caddy-kong-middleware-odoo-contract-certification",
    "negative-authorization-and-tenant-isolation",
    "representative-database-filestore-restore", "rollback-rehearsal",
    "production-read-only-canary", "bounded-production-soak",
    "production-activation-approval",
}
ACTION = re.compile(r"uses:\s+actions/[A-Za-z0-9_.-]+@[0-9a-f]{40}(?:\s+#.*)?$")


def text(path: Path, errors: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"cannot read {path.relative_to(ROOT)}: {exc}")
        return ""


def load(path: Path, errors: list[str]) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"cannot load {path.relative_to(ROOT)}: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{path.relative_to(ROOT)} must contain an object")
        return {}
    return value


def exact_set(value: object, expected: set[str], name: str, errors: list[str]) -> None:
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        errors.append(f"{name} must be a string array")
        return
    if len(value) != len(set(value)) or set(value) != expected:
        errors.append(f"{name} does not exactly match the production contract")


def pinned_actions(source: str, name: str, errors: list[str]) -> None:
    lines = [line.strip() for line in source.splitlines() if line.strip().startswith("uses:")]
    if not lines:
        errors.append(f"{name} contains no actions")
    for line in lines:
        if not ACTION.fullmatch(line):
            errors.append(f"{name} action is not GitHub-owned and commit-pinned: {line}")


def require(source: str, items: tuple[str, ...], name: str, errors: list[str]) -> None:
    for item in items:
        if item not in source:
            errors.append(f"{name} is missing {item!r}")


def validate_policy(errors: list[str]) -> None:
    policy = load(POLICY, errors)
    required = {
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
    for key, expected in required.items():
        if policy.get(key) != expected:
            errors.append(f"release policy {key} must be {expected!r}")
    image = policy.get("immutable_image")
    if not isinstance(image, dict) or image != {
        "name": IMAGE, "tag_template": "sha-{source_sha}",
        "platform": "linux/amd64", "base_image": BASE,
    }:
        errors.append("immutable_image does not exactly match the reviewed contract")
    exact_set(policy.get("required_source_gates"), SOURCE_GATES, "required_source_gates", errors)
    exact_set(policy.get("required_runtime_gates"), RUNTIME_GATES, "required_runtime_gates", errors)
    exact_set(policy.get("governed_runtime_flags"), FLAGS, "governed_runtime_flags", errors)
    artifacts = policy.get("candidate_artifacts")
    needed = {
        "immutable OCI image digest", "complete container SPDX SBOM",
        "signed SLSA provenance attestation", "signed SBOM attestation",
        "production candidate manifest", "SHA-256 checksums",
    }
    if not isinstance(artifacts, list) or not needed.issubset(set(artifacts)):
        errors.append("candidate_artifacts omits required signed evidence")


def validate_installer(errors: list[str]) -> None:
    source = text(INSTALLER, errors)
    require(source, (
        TRIVY_VERSION, TRIVY_SHA,
        "aquasecurity/trivy/releases/download/v${TRIVY_VERSION}",
        'actual_sha256="$(sha256sum "$ARCHIVE"',
        'test "$actual_sha256" = "$TRIVY_ARCHIVE_SHA256"',
        'tar -xzf "$ARCHIVE"', '"$INSTALL_DIR/trivy" --version',
    ), str(INSTALLER.relative_to(ROOT)), errors)
    if re.search(r"TRIVY_(?:VERSION|ARCHIVE_SHA256)=.*\$\{\{", source):
        errors.append("Trivy pins must not be supplied by workflow expressions")


def validate_release(errors: list[str]) -> None:
    source = text(RELEASE, errors)
    name = str(RELEASE.relative_to(ROOT))
    require(source, (
        "workflow_dispatch:", "expected_source_sha:",
        "BUILD_SIGNED_PRODUCTION_CANDIDATE", "packages: write",
        "id-token: write", "attestations: write",
        "environment: odoo-production-candidate", "persist-credentials: false",
        'test "$GITHUB_REF_NAME" = "main"',
        'test "$EXPECTED_SOURCE_SHA" = "$GITHUB_SHA"',
        "bash scripts/install_trivy.sh", "bash scripts/run_ci.sh",
        "bash scripts/run_odoo_module_tests.sh",
        "bash scripts/build_release_candidate.sh", "docker login ghcr.io",
        'docker manifest inspect "$IMAGE_TAG"', 'docker push "$IMAGE_TAG"',
        're.findall(r"digest:\\s+(sha256:[0-9a-f]{64})"',
        "Block fixed critical vulnerabilities", "Block secrets embedded in the image",
        "actions/attest-build-provenance@4d101475d8b20a2381f78447822ac1eab6504dd8",
        "actions/attest-sbom@c604332985a26aa8cf1bdc465b92731239ec6b9e",
        "scripts/generate_container_release_manifest.py", "SHA256SUMS",
        "PRODUCTION_DEPLOYED=NO", "LIVE_ODOO_WRITE=false",
    ), name, errors)
    if "${{ github.ref_name }}" in source or "TRIVY_VERSION:" in source or "TRIVY_ARCHIVE_SHA256:" in source:
        errors.append("release workflow must use safe shell context and one shared Trivy installer")
    for trigger in ("pull_request:\n", "schedule:\n"):
        if trigger in source:
            errors.append(f"release workflow contains prohibited trigger {trigger.strip()}")
    for forbidden in ("ssh ", "rsync ", "kubectl ", "docker compose ", "pg_restore", "psql ", "odoo-bin", ":latest", "git push"):
        if forbidden in source.lower():
            errors.append(f"release workflow contains prohibited operation {forbidden.strip()!r}")
    order = [source.find(x) for x in (
        "Run exact-main source validation", "Test Odoo 19 and PostgreSQL runtime",
        "Build deterministic source evidence", "Block fixed critical vulnerabilities",
        "Publish immutable SHA tag and resolve registry digest",
    )]
    if any(x < 0 for x in order) or order != sorted(order):
        errors.append("source/runtime validation and security scans must precede publication")
    pinned_actions(source, name, errors)


def validate_container_ci(errors: list[str]) -> None:
    source = text(CONTAINER_CI, errors)
    name = str(CONTAINER_CI.relative_to(ROOT))
    require(source, (
        "permissions:\n  contents: read", "persist-credentials: false",
        "bash scripts/install_trivy.sh", "docker build \\",
        "deploy/container/Dockerfile", "Block fixed critical vulnerabilities",
        "Block secrets embedded in the image", "Generate container SPDX SBOM",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
    ), name, errors)
    if "TRIVY_VERSION:" in source or "TRIVY_ARCHIVE_SHA256:" in source:
        errors.append("container CI must delegate to the shared Trivy installer")
    for forbidden in ("packages: write", "id-token: write", "docker login", "docker push", "push: true", ":latest"):
        if forbidden in source.lower():
            errors.append(f"container CI contains prohibited {forbidden!r}")
    pinned_actions(source, name, errors)


def validate_static_contracts(errors: list[str]) -> None:
    dockerfile = text(DOCKERFILE, errors)
    require(dockerfile, (
        f"FROM {BASE}", "COPY --chown=odoo:odoo custom-addons/ /mnt/extra-addons/",
        "find /mnt/extra-addons -type l", "USER odoo",
    ), str(DOCKERFILE.relative_to(ROOT)), errors)
    for forbidden in ("apt-get", "apk add", "pip install", "curl ", "wget ", " git clone", ":latest"):
        if forbidden in dockerfile.lower():
            errors.append(f"production Dockerfile contains prohibited {forbidden!r}")
    for path in (STAGING, CANARY):
        source = text(path, errors)
        for flag in FLAGS:
            if f"{flag}=false" not in source:
                errors.append(f"{path.relative_to(ROOT)} is missing {flag}=false")
    template = load(TEMPLATE, errors)
    if template.get("schema_version") != 1 or template.get("verdict") != "BLOCKED":
        errors.append("production evidence template must be schema 1 and BLOCKED")
    if template.get("source_sha") != "0" * 40:
        errors.append("production evidence template source SHA must be unset")
    image = template.get("image")
    if not isinstance(image, dict) or image.get("digest") != "sha256:" + "0" * 64:
        errors.append("production evidence template image digest must be unset")
    flags = template.get("runtime_flags")
    if not isinstance(flags, dict) or set(flags) != FLAGS or any(v is not False for v in flags.values()):
        errors.append("production evidence template flags must exactly default false")
    candidate = template.get("candidate")
    if not isinstance(candidate, dict) or set(candidate) != {
        "manifest_path", "checksums_path", "provenance_bundle_path",
        "sbom_bundle_path", "provenance_verified", "sbom_verified",
    }:
        errors.append("production evidence template candidate binding is incomplete")
    approval = template.get("activation_approval")
    if not isinstance(approval, dict) or approval.get("approved") is not False:
        errors.append("production evidence template activation approval must default false")
    integration = template.get("integration")
    if not isinstance(integration, dict) or integration.get("negative_authorization_passed") is not False:
        errors.append("production evidence template must include a closed negative-authorization gate")
    for section in ("canary", "soak"):
        value = template.get(section)
        if not isinstance(value, dict) or value.get("duration_minutes") != 0:
            errors.append(f"production evidence template {section} duration must start at zero")


def main() -> int:
    errors: list[str] = []
    validate_policy(errors)
    validate_installer(errors)
    validate_release(errors)
    validate_container_ci(errors)
    validate_static_contracts(errors)
    if errors:
        print("Release policy validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("RELEASE_WORKFLOW_DISPATCH_ONLY=PASS")
    print("RELEASE_SOURCE_IDENTITY=SIGNED_MAIN_ONLY")
    print("RELEASE_ACTIONS=GITHUB_OWNED_AND_COMMIT_PINNED")
    print("TRIVY_BINARY=SHARED_VERSION_AND_SHA256_PINNED_INSTALLER")
    print("ODOO_POSTGRESQL_RUNTIME_GATE=REQUIRED_BEFORE_PUBLICATION")
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
