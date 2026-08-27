#!/usr/bin/env python3
"""Fail CI when Odoo's system-of-record boundary is weakened."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "integration-boundary.json"
BASELINE = ROOT / "config" / "canonical-addon-baseline.json"
DOC = ROOT / "docs" / "INTEGRATION-BOUNDARY.md"
ADDONS = ROOT / "custom-addons"
REQUIRED_OWNERSHIP = {
    "customers_and_contacts", "leads_and_opportunities", "activities_and_campaigns",
    "call_history", "post_call_forms_and_notes", "callbacks_and_appointments",
    "consent_and_communication_preferences", "sms_and_email_history", "delivery_results",
    "agent_and_supervisor_business_views", "business_reporting",
}
REQUIRED_CONTROLS = {
    "dedicated_service_identity", "least_privilege_acl", "tenant_and_company_mapping",
    "versioned_resource_specific_contract", "idempotency", "correlation_id",
    "stable_external_mapping", "audit_trail", "optimistic_concurrency_when_applicable",
}
REQUIRED_EXCLUSIONS = {
    "postgresql_database", "database_dumps", "filestore", "credentials",
    "runtime_edits", "backups",
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
CONNECTION_TOKENS = {
    key: value
    for key, value in FORBIDDEN_TEXT.items()
    if "connection" in value or "engine" in value
}
SQL_EXCEPTION_KINDS = {
    "odoo_cursor_readiness_probe",
    "odoo_cursor_locking",
    "odoo_sql_view",
    "odoo_schema_index",
    "odoo_test_fixture_sql",
}
DRIVER_EXCEPTION_KINDS = {
    "odoo_internal_driver_exception",
    "odoo_test_driver_exception",
}
ALLOWED_EXCEPTION_KINDS = SQL_EXCEPTION_KINDS | DRIVER_EXCEPTION_KINDS


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
    if string_set(
        policy.get("approved_external_write_interfaces"),
        "approved_external_write_interfaces",
        errors,
    ) != {"odoo_service_api", "odoo_orm_bridge"}:
        errors.append("approved interfaces must be exactly the service API and ORM bridge")
    missing = REQUIRED_CONTROLS - string_set(
        policy.get("required_external_write_controls"),
        "required_external_write_controls",
        errors,
    )
    if missing:
        errors.append("missing external-write controls: " + ", ".join(sorted(missing)))
    missing = REQUIRED_OWNERSHIP - string_set(
        policy.get("odoo_owns"), "odoo_owns", errors
    )
    if missing:
        errors.append("missing Odoo ownership: " + ", ".join(sorted(missing)))
    missing = REQUIRED_EXCLUSIONS - string_set(
        policy.get("repository_excludes"), "repository_excludes", errors
    )
    if missing:
        errors.append("missing repository exclusions: " + ", ".join(sorted(missing)))
    bridge = policy.get("orm_bridge")
    if not isinstance(bridge, dict):
        errors.append("orm_bridge must be an object")
        return
    for key in (
        "must_use_odoo_orm_for_business_writes",
        "may_use_migration_sql_inside_reviewed_migrations",
        "must_store_middleware_command_identity_atomically",
        "must_not_expose_arbitrary_model_or_method_parameters",
    ):
        if bridge.get(key) is not True:
            errors.append(f"orm_bridge.{key} must be true")


def git_tree_sha(module_name: str) -> str | None:
    command = subprocess.run(
        ["git", "rev-parse", f"HEAD:custom-addons/{module_name}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return command.stdout.strip() if command.returncode == 0 else None


def safe_module_path(module_name: str, value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or pure.suffix != ".py":
        return None
    candidate = ADDONS / module_name / Path(*pure.parts)
    try:
        candidate.resolve().relative_to((ADDONS / module_name).resolve())
    except (OSError, ValueError):
        return None
    return candidate


def load_review_registry(
    errors: list[str],
) -> tuple[set[str], set[str], dict[str, dict[str, set[str]]]]:
    try:
        payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"cannot load {BASELINE.relative_to(ROOT)}: {exc}")
        return set(), set(), {}

    modules = payload.get("modules")
    overrides = payload.get("strict_mission_overrides")
    if not isinstance(modules, dict):
        errors.append("canonical baseline modules must be an object")
        modules = {}
    if not isinstance(overrides, dict):
        errors.append("strict_mission_overrides must be an object")
        overrides = {}

    pinned: set[str] = set()
    exact_overrides: set[str] = set()
    exception_map: dict[str, dict[str, set[str]]] = {}

    for name, expected in modules.items():
        if isinstance(name, str) and isinstance(expected, str) and git_tree_sha(name) == expected:
            pinned.add(name)

    for name, declaration in overrides.items():
        if not isinstance(name, str) or not isinstance(declaration, dict):
            errors.append(f"invalid strict mission override declaration for {name!r}")
            continue
        current_tree = declaration.get("current_tree")
        actual = git_tree_sha(name)
        if not isinstance(current_tree, str) or actual != current_tree:
            errors.append(
                f"strict mission override {name!r} is not bound to the exact current tree"
            )
            continue
        exact_overrides.add(name)
        path_kinds: dict[str, set[str]] = {}
        seen: set[tuple[str, str]] = set()
        entries = declaration.get("integration_boundary_exceptions", [])
        if not isinstance(entries, list):
            errors.append(
                f"strict mission override {name!r} integration_boundary_exceptions must be a list"
            )
            entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                errors.append(f"{name}: integration-boundary exception must be an object")
                continue
            path_value = entry.get("path")
            kind = entry.get("kind")
            reason = entry.get("reason")
            target = safe_module_path(name, path_value)
            if target is None or not target.is_file() or target.is_symlink():
                errors.append(f"{name}: invalid exception path {path_value!r}")
                continue
            if kind not in ALLOWED_EXCEPTION_KINDS:
                errors.append(f"{name}: unsupported exception kind {kind!r}")
                continue
            if not isinstance(reason, str) or len(reason.strip()) < 20:
                errors.append(f"{name}: exception {path_value!r} requires a specific reason")
                continue
            key = (str(path_value), str(kind))
            if key in seen:
                errors.append(f"{name}: duplicate exception {path_value!r}/{kind!r}")
                continue
            seen.add(key)
            relative = target.relative_to(ADDONS / name).as_posix()
            if kind.startswith("odoo_test_") and "tests" not in target.relative_to(ADDONS / name).parts:
                errors.append(f"{name}: test-only exception is outside tests: {relative}")
                continue
            if kind == "odoo_internal_driver_exception" and "tests" in target.relative_to(ADDONS / name).parts:
                errors.append(f"{name}: runtime driver exception cannot target tests: {relative}")
                continue
            path_kinds.setdefault(relative, set()).add(kind)
        exception_map[name] = path_kinds

    return pinned, exact_overrides, exception_map


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


def attribute_chain(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [*attribute_chain(node.value), node.attr]
    return []


def static_sql(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                parts.append("{EXPRESSION}")
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = static_sql(node.left)
        right = static_sql(node.right)
        return None if left is None or right is None else left + right
    return None


def cursor_sql_statements(path: Path, errors: list[str]) -> list[str | None]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        errors.append(f"cannot parse {path.relative_to(ROOT)}: {exc}")
        return []
    statements: list[str | None] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        chain = attribute_chain(node.func)
        if len(chain) < 2 or chain[-2:] != ["cr", "execute"]:
            continue
        statements.append(static_sql(node.args[0]) if node.args else None)
    return statements


def normalized_sql(statement: str) -> str:
    return " ".join(statement.upper().split())


def validate_sql_exception(
    relative: Path,
    kinds: set[str],
    statements: list[str | None],
    errors: list[str],
) -> None:
    sql_kinds = kinds & SQL_EXCEPTION_KINDS
    if not statements:
        if sql_kinds:
            errors.append(f"{relative}: declared SQL exception is stale")
        return
    if len(sql_kinds) != 1:
        errors.append(
            f"{relative}: raw SQL requires exactly one reviewed SQL exception kind"
        )
        return
    if any(statement is None for statement in statements):
        errors.append(f"{relative}: reviewed SQL must be statically inspectable")
        return
    sql_values = [normalized_sql(statement or "") for statement in statements]
    kind = next(iter(sql_kinds))

    if kind == "odoo_cursor_readiness_probe":
        if any(sql != "SELECT 1" for sql in sql_values):
            errors.append(f"{relative}: readiness exception permits only SELECT 1")
    elif kind == "odoo_cursor_locking":
        if any(not sql.startswith("SELECT ") or ";" in sql for sql in sql_values):
            errors.append(
                f"{relative}: cursor-locking exception permits one SELECT statement only"
            )
        if not any("FOR UPDATE" in sql for sql in sql_values):
            errors.append(f"{relative}: cursor-locking exception requires a FOR UPDATE lock")
    elif kind == "odoo_sql_view":
        allowed = (
            "DROP VIEW IF EXISTS ",
            "SELECT TO_REGCLASS(",
            "CREATE VIEW ",
            "CREATE OR REPLACE VIEW ",
        )
        if any(not sql.startswith(allowed) for sql in sql_values):
            errors.append(f"{relative}: SQL-view exception contains unsupported SQL")
        if not any(sql.startswith(("CREATE VIEW ", "CREATE OR REPLACE VIEW ")) for sql in sql_values):
            errors.append(f"{relative}: SQL-view exception does not create a view")
    elif kind == "odoo_schema_index":
        allowed = ("CREATE UNIQUE INDEX IF NOT EXISTS ", "CREATE INDEX IF NOT EXISTS ")
        if any(not sql.startswith(allowed) for sql in sql_values):
            errors.append(f"{relative}: schema-index exception contains unsupported SQL")
    elif kind == "odoo_test_fixture_sql":
        if "tests" not in relative.parts:
            errors.append(f"{relative}: fixture SQL exception is outside tests")
        forbidden = ("CREATE ", "DROP ", "ALTER ", "TRUNCATE ", "GRANT ", "REVOKE ")
        if any(sql.startswith(forbidden) for sql in sql_values):
            errors.append(f"{relative}: test fixture SQL may not mutate schema or privileges")


def validate_driver_exception(
    relative: Path,
    kinds: set[str],
    forbidden_modules: set[str],
    text: str,
    errors: list[str],
) -> None:
    driver_kinds = kinds & DRIVER_EXCEPTION_KINDS
    if not forbidden_modules:
        if driver_kinds:
            errors.append(f"{relative}: declared database-driver exception is stale")
        return
    if len(driver_kinds) != 1:
        errors.append(
            f"{relative}: database-driver import requires exactly one reviewed exception kind"
        )
        return
    if forbidden_modules != {"psycopg2"}:
        errors.append(
            f"{relative}: reviewed driver exception may cover psycopg2 only; got "
            + ", ".join(sorted(forbidden_modules))
        )
    kind = next(iter(driver_kinds))
    if kind == "odoo_test_driver_exception" and "tests" not in relative.parts:
        errors.append(f"{relative}: test driver exception is outside tests")
    if kind == "odoo_internal_driver_exception" and "tests" in relative.parts:
        errors.append(f"{relative}: runtime driver exception targets a test")
    if "IntegrityError" not in text and "UniqueViolation" not in text:
        errors.append(
            f"{relative}: driver exception is limited to database constraint exception classes"
        )


def validate_addons(errors: list[str]) -> None:
    if not ADDONS.is_dir():
        errors.append("custom-addons directory is missing")
        return
    pinned, overrides, exception_map = load_review_registry(errors)
    used_exceptions: set[tuple[str, str, str]] = set()

    for path in sorted(ADDONS.rglob("*.py")):
        relative = path.relative_to(ROOT)
        module_name = relative.parts[1] if len(relative.parts) > 1 else ""
        module_relative = path.relative_to(ADDONS / module_name).as_posix()
        is_pinned = module_name in pinned
        is_override = module_name in overrides
        kinds = exception_map.get(module_name, {}).get(module_relative, set())
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"cannot read {relative}: {exc}")
            continue
        lowered = text.lower().replace(" ", "")
        tokens = CONNECTION_TOKENS if is_pinned else FORBIDDEN_TEXT
        for token, label in tokens.items():
            if token in lowered:
                errors.append(f"{relative} contains forbidden {label}")
        if is_pinned:
            continue

        forbidden_modules = imported_modules(path, errors) & FORBIDDEN_DB_MODULES
        validate_driver_exception(relative, kinds, forbidden_modules, text, errors)
        if forbidden_modules and kinds & DRIVER_EXCEPTION_KINDS:
            used_exceptions.update(
                (module_name, module_relative, kind)
                for kind in kinds & DRIVER_EXCEPTION_KINDS
            )

        is_migration = any(part in {"migrations", "upgrades"} for part in path.parts)
        statements = [] if is_migration else cursor_sql_statements(path, errors)
        validate_sql_exception(relative, kinds, statements, errors)
        if statements and kinds & SQL_EXCEPTION_KINDS:
            used_exceptions.update(
                (module_name, module_relative, kind)
                for kind in kinds & SQL_EXCEPTION_KINDS
            )

        if not is_override and kinds:
            errors.append(f"{relative}: exceptions require an exact strict mission override")

    for module_name, paths in exception_map.items():
        for module_relative, kinds in paths.items():
            for kind in kinds:
                if (module_name, module_relative, kind) not in used_exceptions:
                    errors.append(
                        f"custom-addons/{module_name}/{module_relative}: unused reviewed exception {kind}"
                    )

    print(f"INTEGRATION_BOUNDARY_PINNED_MODULES={len(pinned)}")
    print(f"INTEGRATION_BOUNDARY_STRICT_OVERRIDES={len(overrides)}")


def validate_bridge_scaffold(errors: list[str]) -> None:
    module = ADDONS / "codestra_integration_bridge"
    if not module.exists():
        return
    for path in (
        module / "__init__.py",
        module / "__manifest__.py",
        module / "security" / "ir.model.access.csv",
    ):
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
        "may write through approved service APIs or the ORM bridge."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
