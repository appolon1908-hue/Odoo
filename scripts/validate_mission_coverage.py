#!/usr/bin/env python3
"""Validate complete source ownership for the corporate call-center mission."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDONS = ROOT / "custom-addons"
COVERAGE = ROOT / "config" / "call-center-module-coverage.json"
REQUIRED_MODULES = {
    "codestra_cc_core",
    "codestra_cc_vicidial",
    "codestra_cc_agent_desktop",
    "codestra_cc_campaign",
    "codestra_cc_disposition",
    "codestra_cc_customer_360",
    "codestra_cc_supervisor",
    "codestra_cc_quality",
    "codestra_cc_compliance",
    "codestra_cc_omnichannel",
    "codestra_cc_workforce",
    "codestra_cc_identity",
    "codestra_cc_mailbox",
    "codestra_cc_automation",
    "codestra_cc_reliability",
    "codestra_cc_analytics",
    "codestra_cc_audit",
    "codestra_client_operations",
    "codestra_revenue_assurance",
    "codestra_data_quality",
    "codestra_case_management",
    "codestra_agent_onboarding",
    "codestra_training_academy",
    "codestra_client_portal",
    "codestra_campaign_publishing",
    "codestra_ai_agent_assistant",
}
SCHEMA_MODULES = {
    "codestra_case_management",
    "codestra_cc_workforce",
    "codestra_agent_onboarding",
    "codestra_training_academy",
    "codestra_client_operations",
    "codestra_revenue_assurance",
    "codestra_data_quality",
    "codestra_ai_agent_assistant",
}
PORTAL_MODULES = {"codestra_client_portal"}


def load_manifest(path: Path) -> dict:
    value = ast.literal_eval(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("manifest must be a dictionary")
    return value


def main() -> int:
    errors: list[str] = []
    try:
        payload = json.loads(COVERAGE.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR=cannot load mission coverage: {exc}", file=sys.stderr)
        return 1

    entries = payload.get("coverage", [])
    by_name = {
        item.get("mission_module"): item
        for item in entries
        if isinstance(item, dict) and isinstance(item.get("mission_module"), str)
    }
    if set(by_name) != REQUIRED_MODULES:
        errors.append(
            "mission coverage mismatch: missing="
            + ",".join(sorted(REQUIRED_MODULES - set(by_name)))
            + " extra="
            + ",".join(sorted(set(by_name) - REQUIRED_MODULES))
        )
    if len(entries) != len(by_name):
        errors.append("mission coverage contains duplicate or invalid entries")

    for name in sorted(REQUIRED_MODULES):
        module = ADDONS / name
        manifest_path = module / "__manifest__.py"
        for required in (module / "__init__.py", manifest_path, module / "README.md"):
            if not required.is_file():
                errors.append(f"{name}: missing {required.relative_to(module)}")
        if not manifest_path.is_file():
            continue
        try:
            manifest = load_manifest(manifest_path)
        except (OSError, SyntaxError, ValueError) as exc:
            errors.append(f"{name}: invalid manifest: {exc}")
            continue
        if manifest.get("installable") is not True:
            errors.append(f"{name}: module must remain installable")
        if not str(manifest.get("version", "")).startswith("19.0."):
            errors.append(f"{name}: module must target Odoo 19")
        tests = module / "tests"
        if not tests.is_dir() or not (tests / "__init__.py").is_file() or not list(tests.glob("test_*.py")):
            errors.append(f"{name}: Odoo tests are required")

        entry = by_name.get(name, {})
        if entry.get("source_status") != "implemented":
            errors.append(f"{name}: source_status must be implemented")
        if entry.get("runtime_status") != "pending":
            errors.append(f"{name}: runtime_status must remain pending until evidence exists")
        if not isinstance(entry.get("owner_branch"), str) or not entry["owner_branch"]:
            errors.append(f"{name}: owner_branch is required")
        implementations = entry.get("implementation_modules")
        if not isinstance(implementations, list) or not implementations or not all(
            isinstance(item, str) and item for item in implementations
        ):
            errors.append(f"{name}: implementation_modules must be a non-empty string list")

        expected_type = (
            "schema" if name in SCHEMA_MODULES else "portal" if name in PORTAL_MODULES else "facade"
        )
        if entry.get("implementation_type") != expected_type:
            errors.append(
                f"{name}: implementation_type must be {expected_type!r}, got {entry.get('implementation_type')!r}"
            )

    for name in sorted(SCHEMA_MODULES):
        module = ADDONS / name
        if not (module / "models").is_dir():
            errors.append(f"{name}: schema module is missing models")
        if not (module / "security" / "ir.model.access.csv").is_file():
            errors.append(f"{name}: schema module is missing ACLs")
        if not (module / "security" / "record_rules.xml").is_file():
            errors.append(f"{name}: schema module is missing record rules")
        if not (module / "migrations" / "README.md").is_file():
            errors.append(f"{name}: schema module is missing migration policy")

    if errors:
        print("Mission coverage validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(f"MISSION_MODULES={len(REQUIRED_MODULES)}")
    print(f"MISSION_SCHEMA_MODULES={len(SCHEMA_MODULES)}")
    print("MISSION_SOURCE_COVERAGE=PASS")
    print("MISSION_RUNTIME_CERTIFICATION=PENDING")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
