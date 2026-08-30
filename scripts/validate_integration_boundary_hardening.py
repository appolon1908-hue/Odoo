#!/usr/bin/env python3
"""Reject bypasses not safely covered by the original Odoo boundary validator.

This companion gate closes the historical review gaps for shell/config database
access, Odoo ``sql_db`` connection helpers, cursor aliases, environment aliases,
generic model proxy controllers, unloaded bridge ACLs and placeholder-only
bridge tests.
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
PSQL_TOKEN = re.compile(
    r"(?i)(?:^|[\s;&|`(])(?:[A-Za-z0-9_./-]+/)?psql(?:[\s;&|`)]|$)"
)
DB_CREDENTIAL = re.compile(
    r"(?i)(?:\bPGPASSWORD\s*=|\bDATABASE_URL\s*=|postgres(?:ql)?://)"
)
REQUIRED_BRIDGE_TEST_MARKERS = {
    "signature": {"signature", "signed"},
    "tenant": {"tenant"},
    "idempotency": {"idempotency", "duplicate", "replay"},
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


def assigned_name(node: ast.AST) -> str | None:
    return node.id if isinstance(node, ast.Name) else None


def static_text(node: ast.AST, constants: dict[str, str]) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values = [static_text(item, constants) for item in node.elts]
        return None if any(value is None for value in values) else " ".join(values)  # type: ignore[arg-type]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = static_text(node.left, constants)
        right = static_text(node.right, constants)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                resolved = static_text(value.value, constants)
                if resolved is None:
                    return None
                parts.append(resolved)
            else:
                return None
        return "".join(parts)
    return None


def static_assignments(tree: ast.AST) -> dict[str, str]:
    constants: dict[str, str] = {}
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            target: ast.AST | None = None
            value: ast.AST | None = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target, value = node.targets[0], node.value
            elif isinstance(node, ast.AnnAssign):
                target, value = node.target, node.value
            if target is None or value is None:
                continue
            name = assigned_name(target)
            resolved = static_text(value, constants)
            if name and resolved is not None and constants.get(name) != resolved:
                constants[name] = resolved
                changed = True
    return constants


def git_tree_sha(root: Path, module_name: str) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", f"HEAD:custom-addons/{module_name}"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def reviewed_sql_policy(root: Path) -> tuple[set[str], set[str], set[str]]:
    """Return exact reviewed module trees and path-specific SQL exceptions.

    A pinned or strict-override module is exempt only while its complete subtree
    equals the reviewed tree SHA. Any future source change invalidates that
    exemption automatically and the scanner evaluates every cursor call again.
    """

    baseline_path = root / "config" / "canonical-addon-baseline.json"
    try:
        payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return set(), set(), set()

    pinned: set[str] = set()
    for module_name, expected_tree in payload.get("modules", {}).items():
        if (
            isinstance(module_name, str)
            and isinstance(expected_tree, str)
            and git_tree_sha(root, module_name) == expected_tree
        ):
            pinned.add(module_name)

    exact_overrides: set[str] = set()
    exceptions: set[str] = set()
    for module_name, declaration in payload.get("strict_mission_overrides", {}).items():
        if not isinstance(module_name, str) or not isinstance(declaration, dict):
            continue
        current_tree = declaration.get("current_tree")
        if not isinstance(current_tree, str) or git_tree_sha(root, module_name) != current_tree:
            continue
        exact_overrides.add(module_name)
        for entry in declaration.get("integration_boundary_exceptions", []):
            if not isinstance(entry, dict) or entry.get("kind") not in SQL_EXCEPTION_KINDS:
                continue
            path = entry.get("path")
            if isinstance(path, str) and path and ".." not in Path(path).parts:
                exceptions.add(f"{module_name}/{Path(path).as_posix()}")
    return pinned, exact_overrides, exceptions


def is_direct_cursor_expression(node: ast.AST, aliases: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in aliases
    chain = attribute_chain(node)
    if not chain:
        return False
    if chain[-1] == "_cr" and chain[0] == "self":
        return True
    return chain[-1] == "cr" and ("env" in chain or len(chain) == 1)


def cursor_aliases(tree: ast.AST) -> set[str]:
    aliases = {"cr", "_cr"}
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            target: ast.AST | None = None
            value: ast.AST | None = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target, value = node.targets[0], node.value
            elif isinstance(node, ast.AnnAssign):
                target, value = node.target, node.value
            if target is None or value is None:
                continue
            name = assigned_name(target)
            if name and name not in aliases and is_direct_cursor_expression(value, aliases):
                aliases.add(name)
                changed = True
    return aliases


def is_cursor_execute(call: ast.Call, aliases: set[str]) -> bool:
    return (
        isinstance(call.func, ast.Attribute)
        and call.func.attr == "execute"
        and is_direct_cursor_expression(call.func.value, aliases)
    )


def is_environment_expression(node: ast.AST, aliases: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in aliases
    chain = attribute_chain(node)
    return chain[-2:] in (["request", "env"], ["self", "env"])


def environment_aliases(tree: ast.AST) -> set[str]:
    aliases: set[str] = set()
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            target: ast.AST | None = None
            value: ast.AST | None = None
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target, value = node.targets[0], node.value
            elif isinstance(node, ast.AnnAssign):
                target, value = node.target, node.value
            if target is None or value is None:
                continue
            name = assigned_name(target)
            if name and name not in aliases and is_environment_expression(value, aliases):
                aliases.add(name)
                changed = True
    return aliases


def dynamic_model_parameter(node: ast.AST, env_aliases: set[str]) -> str | None:
    selector: ast.AST | None = None
    if isinstance(node, ast.Subscript) and is_environment_expression(node.value, env_aliases):
        selector = node.slice
    elif (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "__getitem__"
        and is_environment_expression(node.func.value, env_aliases)
        and node.args
    ):
        selector = node.args[0]
    if selector is None or static_string(selector) is not None:
        return None
    return selector.id if isinstance(selector, ast.Name) else ""


def function_parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    return [
        argument.arg
        for argument in (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        )
    ]


def static_model_wrapper_parameters(
    tree: ast.AST,
    env_aliases: set[str],
) -> set[tuple[str, str]]:
    """Recognize private wrappers whose every in-file caller passes literals."""

    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    safe: set[tuple[str, str]] = set()
    for name, function in functions.items():
        parameters = function_parameters(function)
        candidates = {
            parameter
            for child in ast.walk(function)
            for parameter in [dynamic_model_parameter(child, env_aliases)]
            if parameter and parameter in parameters
        }
        for parameter in candidates:
            parameter_index = parameters.index(parameter)
            observed = 0
            unsafe = False
            for call in ast.walk(tree):
                if not isinstance(call, ast.Call):
                    continue
                chain = attribute_chain(call.func)
                if not chain or chain[-1] != name:
                    continue
                observed += 1
                value = next(
                    (
                        keyword.value
                        for keyword in call.keywords
                        if keyword.arg == parameter
                    ),
                    None,
                )
                if value is None:
                    positional_index = parameter_index
                    if (
                        isinstance(call.func, ast.Attribute)
                        and parameters
                        and parameters[0] in {"self", "cls"}
                    ):
                        positional_index -= 1
                    if positional_index < 0 or positional_index >= len(call.args):
                        unsafe = True
                        break
                    value = call.args[positional_index]
                if static_string(value) is None:
                    unsafe = True
                    break
            if observed and not unsafe:
                safe.add((name, parameter))
    return safe


def parent_functions(tree: ast.AST) -> dict[ast.AST, ast.FunctionDef | ast.AsyncFunctionDef]:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    result: dict[ast.AST, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in ast.walk(tree):
        current = parents.get(node)
        while current is not None:
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                result[node] = current
                break
            current = parents.get(current)
    return result


def process_command_node(call: ast.Call) -> ast.AST | None:
    if call.args:
        return call.args[0]
    return next(
        (
            keyword.value
            for keyword in call.keywords
            if keyword.arg in {"args", "command"}
        ),
        None,
    )


def python_findings(path: Path, *, allow_cursor_sql: bool) -> list[str]:
    findings: list[str] = []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        return [f"cannot parse Python source: {exc}"]

    constants = static_assignments(tree)
    cursor_names = cursor_aliases(tree)
    env_names = environment_aliases(tree)
    safe_wrappers = static_model_wrapper_parameters(tree, env_names)
    enclosing = parent_functions(tree)
    sql_db_aliases: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "odoo.sql_db":
            for alias in node.names:
                if alias.name in ODOO_SQL_DB_HELPERS or alias.name == "*":
                    findings.append(
                        f"Odoo sql_db helper import is prohibited: {alias.name}"
                    )
                sql_db_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "odoo.sql_db":
                    sql_db_aliases.add(alias.asname or alias.name)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            chain = attribute_chain(node.func)
            if (
                chain
                and chain[-1] in ODOO_SQL_DB_HELPERS
                and (
                    chain[-1] in sql_db_aliases
                    or "sql_db" in chain
                    or chain[0] in sql_db_aliases
                )
            ):
                findings.append(
                    f"separate Odoo sql_db connection helper is prohibited: {'.'.join(chain)}"
                )
            if is_cursor_execute(node, cursor_names) and not allow_cursor_sql:
                findings.append(
                    f"undeclared Odoo cursor execution is prohibited: {'.'.join(chain)}"
                )
            if chain and chain[-1] in PROCESS_CALLS:
                command_node = process_command_node(node)
                command_text = (
                    static_text(command_node, constants)
                    if command_node is not None
                    else None
                )
                if command_text is None:
                    findings.append(
                        "unanalyzable process invocation is prohibited in Odoo addons"
                    )
                else:
                    if PSQL_TOKEN.search(command_text):
                        findings.append("Python process invocation of psql is prohibited")
                    if DB_CREDENTIAL.search(command_text):
                        findings.append(
                            "Python process invocation contains database credentials"
                        )

        if "controllers" in path.parts:
            parameter = dynamic_model_parameter(node, env_names)
            if parameter is None:
                continue
            function = enclosing.get(node)
            if (
                parameter
                and function is not None
                and (function.name, parameter) in safe_wrappers
            ):
                continue
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


def meaningful_test_method(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            if not (
                isinstance(child.test, ast.Constant)
                and child.test.value is True
            ):
                return True
        if not isinstance(child, ast.Call):
            continue
        chain = attribute_chain(child.func)
        name = chain[-1] if chain else ""
        if name in {"assertRaises", "assertRaisesRegex", "assertWarns"}:
            return True
        if not name.startswith("assert"):
            continue
        if name == "assertTrue" and child.args:
            if isinstance(child.args[0], ast.Constant) and child.args[0].value is True:
                continue
        if name == "assertFalse" and child.args:
            if isinstance(child.args[0], ast.Constant) and child.args[0].value is False:
                continue
        if name in {"assertEqual", "assertIs"} and len(child.args) >= 2:
            if (
                isinstance(child.args[0], ast.Constant)
                and isinstance(child.args[1], ast.Constant)
                and child.args[0].value == child.args[1].value
            ):
                continue
        return True
    return False


def semantic_test_tokens(tree: ast.AST) -> set[str]:
    tokens: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            tokens.add(node.id.lower())
        elif isinstance(node, ast.Attribute):
            tokens.add(node.attr.lower())
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            tokens.add(node.name.lower())
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            tokens.update(re.findall(r"[a-z0-9_]+", node.value.lower()))
    return tokens


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
    imported = set(
        re.findall(r"from\s+\.\s+import\s+(test_[A-Za-z0-9_]+)", init_text)
    )
    if not imported:
        findings.append("bridge tests/__init__.py imports no test modules")
        return findings

    meaningful_methods = 0
    test_classes = 0
    tokens: set[str] = set()
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
        tokens.update(semantic_test_tokens(tree))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {
                attribute_chain(base)[-1]
                for base in node.bases
                if attribute_chain(base)
            }
            if not bases & ODOO_TEST_BASES:
                continue
            test_classes += 1
            meaningful_methods += sum(
                isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name.startswith("test_")
                and meaningful_test_method(item)
                for item in node.body
            )
    if test_classes == 0 or meaningful_methods == 0:
        findings.append(
            "bridge tests contain no meaningful discoverable Odoo test case methods"
        )
    for label, alternatives in REQUIRED_BRIDGE_TEST_MARKERS.items():
        if not tokens & alternatives:
            findings.append(
                f"bridge tests do not cover required control marker: {label}"
            )
    return findings


def scan_repository(root: Path = ROOT) -> list[str]:
    addons = root / "custom-addons"
    pinned, exact_overrides, sql_exceptions = reviewed_sql_policy(root)
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
            allow_sql = (
                module_name in pinned
                or module_name in exact_overrides
                or relative.as_posix() in sql_exceptions
            )
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
