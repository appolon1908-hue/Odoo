#!/usr/bin/env python3
"""Validate Codestra Odoo production-certification policy and evidence.

The policy file is intentionally fail-closed. A production evidence bundle can
only certify one protected-main source SHA and one immutable runtime digest.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "config" / "production-certification.v1.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ALLOWED_GATE_STATUS = {"PASS", "BLOCKED", "FAIL"}


class CertificationError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CertificationError(f"cannot load {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CertificationError(f"{path} must contain a JSON object")
    return payload


def validate_policy(policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if policy.get("schema_version") != 1:
        errors.append("policy schema_version must equal 1")
    if policy.get("system") != "codestra-odoo-19":
        errors.append("policy system must equal codestra-odoo-19")
    if policy.get("authoritative_repository") != "appolon1908-hue/Odoo":
        errors.append("authoritative_repository must equal appolon1908-hue/Odoo")
    if policy.get("candidate_branch") != "main":
        errors.append("candidate_branch must equal main")
    if policy.get("production_certified") is not False:
        errors.append("repository policy must default production_certified to false")
    if policy.get("default_verdict") != "NO_GO":
        errors.append("repository policy must default to NO_GO")

    expected_true = {
        "source_sha_must_be_protected_main",
        "runtime_artifact_must_be_immutable",
        "evidence_must_bind_to_same_source_sha_and_artifact_digest",
        "production_promotion_must_be_separate_from_source_merge",
    }
    expected_false = {
        "administrator_bypass_allowed",
        "mutable_image_tags_allowed",
        "direct_external_postgresql_writes_allowed",
        "odoo_write_default",
        "external_delivery_default",
        "pstn_dialing_default",
    }
    controls = policy.get("policy")
    if not isinstance(controls, dict):
        errors.append("policy must be an object")
    else:
        for key in sorted(expected_true):
            if controls.get(key) is not True:
                errors.append(f"policy.{key} must be true")
        for key in sorted(expected_false):
            if controls.get(key) is not False:
                errors.append(f"policy.{key} must be false")

    gates = policy.get("required_gates")
    required = {
        "source_ci",
        "immutable_artifact",
        "supply_chain",
        "isolated_staging",
        "backup_restore",
        "rollback",
        "canary_and_soak",
        "governance",
        "production_activation",
    }
    if not isinstance(gates, dict):
        errors.append("required_gates must be an object")
        return errors
    missing = required - set(gates)
    extra = set(gates) - required
    if missing:
        errors.append("missing required gates: " + ", ".join(sorted(missing)))
    if extra:
        errors.append("unknown required gates: " + ", ".join(sorted(extra)))
    for name, gate in gates.items():
        if not isinstance(gate, dict):
            errors.append(f"required_gates.{name} must be an object")
            continue
        if gate.get("status") not in {"REQUIRED", "BLOCKED"}:
            errors.append(f"required_gates.{name}.status must be REQUIRED or BLOCKED")
        evidence = gate.get("evidence")
        if not isinstance(evidence, list) or not evidence or not all(
            isinstance(item, str) and item.strip() for item in evidence
        ):
            errors.append(f"required_gates.{name}.evidence must be a non-empty string list")
    return errors


def validate_evidence(
    evidence: dict[str, Any],
    required_gates: set[str],
    expected_source_sha: str | None,
) -> list[str]:
    errors: list[str] = []
    if evidence.get("schema_version") != 1:
        errors.append("evidence schema_version must equal 1")
    if evidence.get("system") != "codestra-odoo-19":
        errors.append("evidence system must equal codestra-odoo-19")
    if evidence.get("repository") != "appolon1908-hue/Odoo":
        errors.append("evidence repository must equal appolon1908-hue/Odoo")
    if evidence.get("source_branch") != "main":
        errors.append("evidence source_branch must equal main")

    source_sha = evidence.get("source_sha")
    if not isinstance(source_sha, str) or not SHA_RE.fullmatch(source_sha):
        errors.append("source_sha must be a lowercase 40-character Git SHA")
    elif expected_source_sha and source_sha != expected_source_sha:
        errors.append(
            f"source_sha {source_sha} does not match expected SHA {expected_source_sha}"
        )

    artifact_digest = evidence.get("artifact_digest")
    if not isinstance(artifact_digest, str) or not DIGEST_RE.fullmatch(artifact_digest):
        errors.append("artifact_digest must be sha256:<64 lowercase hex characters>")

    release_version = evidence.get("release_version")
    if not isinstance(release_version, str) or not release_version.strip():
        errors.append("release_version is required")

    gates = evidence.get("gates")
    if not isinstance(gates, dict):
        errors.append("gates must be an object")
        return errors
    missing = required_gates - set(gates)
    extra = set(gates) - required_gates
    if missing:
        errors.append("evidence is missing gates: " + ", ".join(sorted(missing)))
    if extra:
        errors.append("evidence contains unknown gates: " + ", ".join(sorted(extra)))

    for name in sorted(required_gates & set(gates)):
        gate = gates[name]
        if not isinstance(gate, dict):
            errors.append(f"gates.{name} must be an object")
            continue
        status = gate.get("status")
        if status not in ALLOWED_GATE_STATUS:
            errors.append(f"gates.{name}.status must be PASS, BLOCKED, or FAIL")
        if gate.get("source_sha") != source_sha:
            errors.append(f"gates.{name}.source_sha must match the top-level source_sha")
        if gate.get("artifact_digest") != artifact_digest:
            errors.append(
                f"gates.{name}.artifact_digest must match the top-level artifact_digest"
            )
        refs = gate.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            errors.append(f"gates.{name}.evidence_refs must be a non-empty list")
        elif not all(
            isinstance(item, dict)
            and isinstance(item.get("reference"), str)
            and item["reference"].strip()
            and isinstance(item.get("sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
            for item in refs
        ):
            errors.append(
                f"gates.{name}.evidence_refs entries require reference and 64-hex sha256"
            )

    all_pass = bool(required_gates) and all(
        isinstance(gates.get(name), dict) and gates[name].get("status") == "PASS"
        for name in required_gates
    )
    certified = evidence.get("production_certified")
    verdict = evidence.get("verdict")
    if certified is True and not all_pass:
        errors.append("production_certified cannot be true unless every gate is PASS")
    if all_pass and certified is not True:
        errors.append("production_certified must be true when every required gate is PASS")
    if certified is True and verdict != "GO":
        errors.append("verdict must be GO when production_certified is true")
    if certified is not True and verdict != "NO_GO":
        errors.append("verdict must be NO_GO while production_certified is not true")
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--expected-source-sha")
    parser.add_argument("--assert-certified", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    policy = load_json(args.policy)
    errors = validate_policy(policy)
    if args.expected_source_sha and not SHA_RE.fullmatch(args.expected_source_sha):
        errors.append("--expected-source-sha must be a lowercase 40-character Git SHA")

    evidence: dict[str, Any] | None = None
    if args.evidence:
        evidence = load_json(args.evidence)
        required_gates = set(policy.get("required_gates", {}))
        errors.extend(
            validate_evidence(evidence, required_gates, args.expected_source_sha)
        )
        if args.assert_certified and evidence.get("production_certified") is not True:
            errors.append("production evidence is not certified")
    elif args.assert_certified:
        errors.append("--assert-certified requires --evidence")

    for error in errors:
        print(f"ERROR={error}", file=sys.stderr)
    if errors:
        print("PRODUCTION_CERTIFICATION_POLICY=FAIL")
        return 1

    print("PRODUCTION_CERTIFICATION_POLICY=PASS")
    if evidence is None:
        print("PRODUCTION_CERTIFIED=NO")
        print("PRODUCTION_VERDICT=NO_GO")
    else:
        certified = evidence.get("production_certified") is True
        print(f"PRODUCTION_CERTIFIED={'YES' if certified else 'NO'}")
        print(f"PRODUCTION_VERDICT={evidence.get('verdict')}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CertificationError as exc:
        print(f"ERROR={exc}", file=sys.stderr)
        raise SystemExit(1)
