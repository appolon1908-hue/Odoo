#!/usr/bin/env python3
"""Fail CI when Odoo's system-of-record boundary is weakened."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "integration-boundary.json"
DOC = ROOT / "docs" / "INTEGRATION-BOUNDARY.md"
ADDONS = ROOT / "custom-addons"

REQUIRED_OWNERSHIP = {
    "customers_and_contacts",
    "leads_and_opportunities",
    "activities_and_campaigns",
    "call_history",
    "post_call_forms_and_notes",
    "callbacks_and_appointments",
    "consent_and_communication_preferences",
    "sms_and_email_history",
    "delivery_results",
    "agent_and_supervisor_business_views",
    "business_reporting",
}
REQUIRED_CONTROLS = {
    "dedicated_service_identity",
    "least_privilege_acl",
    "tenant_and_company_mapping",
    "versioned_resource_specific_contract",
    "idempotency",
    "correlation_id",
    "stable_external_mapping",
    "audit_trail",
    "optimistic_concurrency_when_applicable",
}
REQUIRED_EXCLUSIONS = {
    "postgresql_database",
    "database_dumps",
    "filestore",
    "credentials",
    "runtime_edits",
    "backups",
}
FORBIDDEN_DB_MODULES = {"asyncpg", "pg8000", "psycopg", "psycopg2", "sqlalchemy"}
FORBIDDEN_TEXT = {
    "database_url": "database credential variable",
    "pgpassword": "database credential variable",
    "odoo_db_host": "Odoo database credential variable",
    "odoo_db_user": "Odoo database credential variable",
    "odoo_db_password": "Odoo database credential variable",
    "odoo_database_url": "Odoo database credential variable",
    "psycopg.connect(": "external PostgreSQL connection",
    "psycopg2.connect(": "external PostgreSQL connection",
    "asyncpg.connect(": "external PostgreSQL connection",
    "pg8000.connect(": "external PostgreSQL connection",
    "create_engine(": "external SQLAlchemy engine",
}


def string_set(value: object, name: str, errors: list[str]) -> set[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        errors.append(f"{name} must be an array of strings")
        return set()
    if len(value) != len(set(value)):
        errors.append(f"{name} contains duplicates")
    return set(value)


def validate_policy(errors: list[str]) -> None:
    try:
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"cannot load {POLICY.relative_to(ROOT)}: {exc}")
        return
    if not isinstance(policy, dict):
        errors.append("integration-boundary policy root must be an object")
        return

    expected = {
        "version": 1,
        "system": "odoo-19",
        "system_role": "business_system_of_record",
        "authorized_cross_system_writer": "codestra-middleware",
        "direct_external_postgresql_writes_allowed": False,
        "external_services_may_receive_database_credentials": False,
        "generic_model_write_endpoint_allowed": False,
    }
    for key, value in expected.items():
        if policy.get(key) != value:
            errors.append(f"{key} must be exactly {value!r}")

    interfaces = string_set(
        policy.get("approved_external_write_interfaces"),
        "approved_external_write_interfaces",
        errors,
    )
    if interfaces != {"odoo_service_api", "odoo_orm_bridge"}:
        errors.append("approved interfaces must be exactly the service API and ORM bridge")

    missing_controls = REQUIRED_CONTROLS - string_set(
        policy.get("required_external_write_controls"),
        "required_external_write_controls",
        errors,
    )
    if missing_controls:
        errors.append("missing external-write controls: " + ", ".join(sorted(missing_controls)))

    missing_ownership = REQUIRED_OWNERSHIP - string_set(
        policy.get("odoo_owns"), "odoo_owns", errors
    )
    if missing_ownership:
        errors.append("missing Odoo ownership: " + ", ".join(sorted(missing_ownership)))

    missing_exclusions = REQUIRED_EXCLUSIONS - string_set(
        policy.get("repository_excludes"), "repository_excludes", errors
    )
    if missing_exclusions:
        errors.append("missing repository exclusions: " + ", ".join(sorted(missing_exclusions)))

    bridge = policy.get("orm_bridge")
    if not isinstance(bridge, dict):
        errors.append("orm_bridge must be an object")
        return
    if bridge.get("planned_module_name") != "codestra_integration_bridge":
        errors.append("planned bridge module must be codestra_integration_bridge")
    for key in (
        "must_use_odoo_orm_for_business_writes",
        "may_use_migration_sql_inside_reviewed_migrations",
        "must_store_middleware_command_identity_atomically",
        "must_not_expose_arbitrary_model_or_method_parameters",
    ):
        if bridge.get(key) is not True:
            errors.append(f"orm_bridge.{key} must be true")


def imported_modules(path: Path, errors: list[str]) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        errors.append(f"cannot parse {path.relative_to(ROOT)}: {exc}")
        return set()
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".", 1)[0])
    return modules


def validate_addons(errors: list[str]) -> None:
    if not ADDONS.is_dir():
        errors.append("custom-addons directory is missing")
        return
    for path in sorted(ADDONS.rglob("*.py")):
        relative = path.relative_to(ROOT)
        forbidden = imported_modules(path, errors) & FORBIDDEN_DB_MODULES
        if forbidden:
            errors.append(
                f"{relative} imports external database clients: "
                + ", ".join(sorted(forbidden))
            )
        try:
            lowered = path.read_text(encoding="utf-8").lower().replace(" ", "")
        except (OSError, UnicodeError) as exc:
            errors.append(f"cannot read {relative}: {exc}")
            continue
        for token, label in FORBIDDEN_TEXT.items():
            if token in lowered:
                errors.append(f"{relative} contains forbidden {label}")
        is_migration = any(part in {"migrations", "upgrades"} for part in path.parts)
        if not is_migration and ("env.cr.execute(" in lowered or "request.env.cr.execute(" in lowered):
            errors.append(f"{relative} uses raw SQL outside migrations/upgrades")


def validate_bridge_scaffold(errors: list[str]) -> None:
    module = ADDONS / "codestra_integration_bridge"
    if not module.exists():
        return
    required = (
        module / "__init__.py",
        module / "__manifest__.py",
        module / "security" / "ir.model.access.csv",
    )
    for path in required:
        if not path.is_file():
            errors.append(f"bridge is missing {path.relative_to(ROOT)}")
    tests = module / "tests"
    if not tests.is_dir() or not any(tests.glob("test_*.py")):
        errors.append("codestra_integration_bridge must include Odoo tests")


def validate_document(errors: list[str]) -> None:
    try:
        text = DOC.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"cannot read {DOC.relative_to(ROOT)}: {exc}")
        return
    for phrase in (
        "Codestra Middleware is the only authorized cross-system writer",
        "No external service may write directly to Odoo PostgreSQL",
        "generic database proxy",
    ):
        if phrase not in text:
            errors.append(f"integration-boundary document is missing: {phrase}")


def main() -> int:
    errors: list[str] = []
    validate_policy(errors)
    validate_document(errors)
    validate_addons(errors)
    validate_bridge_scaffold(errors)
    if errors:
        print("Odoo integration-boundary validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(
        "Odoo integration-boundary validation passed: only Codestra Middleware "
        "may write through the approved service API or ORM bridge."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
