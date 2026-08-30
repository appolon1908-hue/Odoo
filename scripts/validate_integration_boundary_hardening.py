#!/usr/bin/env python3
"""Reject bypasses not safely covered by the original Odoo boundary validator.

This companion gate closes the historical review gaps for shell/config database
access, Odoo ``sql_db`` connection helpers, cursor aliases, generic model proxy
controllers, unloaded bridge ACLs and placeholder-only bridge tests.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
ADDONS = ROOT / "custom-addons"
BASELINE = ROOT / "config" / "canonical-addon-baseline.json"
BRIDGE = ADDONS / "codestra_middleware_bridge"

SQL_EXCEPTION_KINDS = {
    "odoo_cursor_readiness_probe",
    "odoo_cursor_locking",
    "odoo_sql_view",
    "odoo_schema_index",
    "odoo_test_fixture_sql",
}
ODOO_SQL_DB_HELPERS = {
    "db_connect",
    "ConnectionPool",
    "Connection",
    "connection_info_for",
}
PROCESS_CALLS = {
    "run",
    "Popen",
    "call",
    "check_call",
    "check_output",
    "system",
    "popen",
}
CONFIG_SUFFIXES = {
    "",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".service",
    ".env",
}
PSQL_TOKEN = re.compile(r"(?i)(?:^|[\s;&|`(])(?:[A-Za-z0-9_./-]+/)?psql(?:[\s;&|`)]|$)")
DB_CREDENTIAL = re.compile(
    r"(?i)(?:\bPGPASSWORD\s*=|\bDATABASE_URL\s*=|postgres(?:ql)?://)"
)
REQUIRED_BRIDGE_TEST_MARKERS = {
    "signature",
    "tenant",
    "idempotency",
}
ODOO_TEST_BASES = {
    "TransactionCase",
    "SavepointCase",
    "HttpCase",
    "SingleTransactionCase",
}


def attribute_chain(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [*attribute_chain(node.value), node.attr]
    return []


def literal_strings(node: ast.AST) -> Iterable[str]:
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            yield child.value


def static_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def git_tree_sha(root: Path, module_name: str) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", f"HEAD:custom-addons/{module_name}"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def reviewed_sql_policy(root: Path) -> tuple[set[str], set[str]]:
    """Return exact pinned modules and exact path-specific SQL exceptions."""
    baseline_path = root / "config" / "canonical-addon-baseline.json"
    try:
        payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return set(), set()

    pinned: set[str] = set()
    for module_name, expected_tree in payload.get("modules", {}).items():
        if (
            isinstance(module_name, str)
            and isinstance(expected_tree, str)
            and git_tree_sha(root, module_name) == expected_tree
        ):
            pinned.add(module_name)

    exceptions: set[str] = set()
    for module_name, declaration in payload.get("strict_mission_overrides", {}).items():
        if not isinstance(module_name, str) or not isinstance(declaration, dict):
            continue
        current_tree = declaration.get("current_tree")
        if not isinstance(current_tree, str) or git_tree_sha(root, module_name) != current_tree:
            continue
        for entry in declaration.get("integration_boundary_exceptions", []):
            if not isinstance(entry, dict) or entry.get("kind") not in SQL_EXCEPTION_KINDS:
                continue
            path = entry.get("path")
            if isinstance(path, str) and path and ".." not in Path(path).parts:
                exceptions.add(f"{module_name}/{Path(path).as_posix()}")
    return pinned, exceptions


def is_cursor_execute(call: ast.Call) -> bool:
    chain = attribute_chain(call.func)
    return len(chain) >= 2 and chain[-1] == "execute" and chain[-2] in {"cr", "_cr"}


def is_dynamic_env_subscript(node: ast.Subscript) -> bool:
    chain = attribute_chain(node.value)
    if chain[-2:] not in (["request", "env"], ["self", "env"]):
        return False
    return static_string(node.slice) is None


def python_findings(path: Path, *, allow_cursor_sql: bool) -> list[str]:
    findings: list[str] = []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        return [f"cannot parse Python source: {exc}"]

    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "odoo.sql_db":
            for alias in node.names:
                if alias.name in ODOO_SQL_DB_HELPERS or alias.name == "*":
                    findings.append(
                        f"Odoo sql_db helper import is prohibited: {alias.name}"
                    )
                aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "odoo.sql_db":
                    aliases.add(alias.asname or alias.name)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            chain = attribute_chain(node.func)
            if (
                chain
                and chain[-1] in ODOO_SQL_DB_HELPERS
                and (chain[-1] in aliases or "sql_db" in chain or chain[0] in aliases)
            ):
                findings.append(
                    f"separate Odoo sql_db connection helper is prohibited: {'.'.join(chain)}"
                )
            if is_cursor_execute(node) and not allow_cursor_sql:
                findings.append(
                    f"undeclared Odoo cursor execution is prohibited: {'.'.join(chain)}"
                )
            if chain and chain[-1] in PROCESS_CALLS:
                command_text = "\n".join(literal_strings(node))
                if PSQL_TOKEN.search(command_text):
                    findings.append("Python process invocation of psql is prohibited")
                if DB_CREDENTIAL.search(command_text):
                    findings.append("Python process invocation contains database credentials")
        elif isinstance(node, ast.Subscript) and "controllers" in path.parts:
            if is_dynamic_env_subscript(node):
                findings.append(
                    "controller uses a caller-selected Odoo model; only static model names are allowed"
                )

    return sorted(set(findings))


def config_findings(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []
    active_lines = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    findings: list[str] = []
    if PSQL_TOKEN.search(active_lines):
        findings.append("shell/config psql invocation is prohibited")
    if DB_CREDENTIAL.search(active_lines):
        findings.append("shell/config database credential or PostgreSQL DSN is prohibited")
    return findings


def bridge_scaffold_findings(root: Path) -> list[str]:
    bridge = root / "custom-addons" / "codestra_middleware_bridge"
    findings: list[str] = []
    manifest_path = bridge / "__manifest__.py"
    try:
        manifest = ast.literal_eval(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError, ValueError) as exc:
        return [f"cannot parse bridge manifest: {exc}"]
    data = manifest.get("data") if isinstance(manifest, dict) else None
    if not isinstance(data, list):
        findings.append("bridge manifest data must be a list")
    else:
        for required in ("security/security.xml", "security/ir.model.access.csv"):
            if required not in data:
                findings.append(f"bridge manifest does not load {required}")

    tests_dir = bridge / "tests"
    init_path = tests_dir / "__init__.py"
    try:
        init_text = init_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        findings.append(f"bridge tests are not discoverable: {exc}")
        return findings
    imported = set(re.findall(r"from\s+\.\s+import\s+(test_[A-Za-z0-9_]+)", init_text))
    if not imported:
        findings.append("bridge tests/__init__.py imports no test modules")
        return findings

    combined = ""
    test_methods = 0
    test_classes = 0
    for module_name in sorted(imported):
        test_path = tests_dir / f"{module_name}.py"
        if not test_path.is_file():
            findings.append(f"bridge test import has no file: {module_name}.py")
            continue
        try:
            text = test_path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(test_path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            findings.append(f"cannot parse bridge test {module_name}: {exc}")
            continue
        combined += "\n" + text.lower()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {attribute_chain(base)[-1] for base in node.bases if attribute_chain(base)}
            if bases & ODOO_TEST_BASES:
                test_classes += 1
                test_methods += sum(
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name.startswith("test_")
                    for item in node.body
                )
    if test_classes == 0 or test_methods == 0:
        findings.append("bridge tests contain no discoverable Odoo test case methods")
    for marker in REQUIRED_BRIDGE_TEST_MARKERS:
        if marker not in combined:
            findings.append(f"bridge tests do not cover required control marker: {marker}")
    return findings


def scan_repository(root: Path = ROOT) -> list[str]:
    addons = root / "custom-addons"
    pinned, sql_exceptions = reviewed_sql_policy(root)
    findings: list[str] = []
    if not addons.is_dir():
        return ["custom-addons directory is missing"]

    for path in sorted(addons.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            relative = path.relative_to(addons)
        except ValueError:
            continue
        module_name = relative.parts[0] if relative.parts else ""
        display = f"custom-addons/{relative.as_posix()}"
        if path.suffix == ".py":
            allow_sql = module_name in pinned or relative.as_posix() in sql_exceptions
            for finding in python_findings(path, allow_cursor_sql=allow_sql):
                findings.append(f"{display}: {finding}")
        elif path.suffix.lower() in CONFIG_SUFFIXES or os.access(path, os.X_OK):
            for finding in config_findings(path):
                findings.append(f"{display}: {finding}")

    for finding in bridge_scaffold_findings(root):
        findings.append(f"custom-addons/codestra_middleware_bridge: {finding}")
    return sorted(set(findings))


def main() -> int:
    findings = scan_repository(ROOT)
    if findings:
        print("INTEGRATION_BOUNDARY_HARDENING=FAIL", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print("INTEGRATION_BOUNDARY_HARDENING=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
