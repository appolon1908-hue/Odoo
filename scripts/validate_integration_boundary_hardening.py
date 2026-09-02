#!/usr/bin/env python3
"""Reject unsafe Odoo integration-boundary bypasses.

The scanner is deliberately conservative but deterministic. It protects the
custom-addon tree from direct PostgreSQL clients, standalone ``odoo.sql_db``
connections, undeclared raw-cursor writes, caller-selected ORM model proxies,
unloaded bridge ACLs, and placeholder-only bridge tests.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDONS = ROOT / "custom-addons"

SQL_EXCEPTION_KINDS = {
    "odoo_cursor_readiness_probe",
    "odoo_cursor_locking",
    "odoo_sql_view",
    "odoo_schema_index",
    "odoo_test_fixture_sql",
    "odoo_schema_migration",
}
ODOO_SQL_DB_HELPERS = {
    "db_connect",
    "ConnectionPool",
    "Connection",
    "connection_info_for",
}
SUBPROCESS_FUNCTIONS = {
    "run",
    "Popen",
    "call",
    "check_call",
    "check_output",
    "getoutput",
    "getstatusoutput",
}
ASYNCIO_PROCESS_FUNCTIONS = {
    "create_subprocess_exec",
    "create_subprocess_shell",
}
OS_PROCESS_FUNCTIONS = {
    "system", "popen",
    "execl", "execle", "execlp", "execlpe",
    "execv", "execve", "execvp", "execvpe",
    "spawnl", "spawnle", "spawnlp", "spawnlpe",
    "spawnv", "spawnve", "spawnvp", "spawnvpe",
    "posix_spawn", "posix_spawnp",
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


def assigned_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        return {name for item in node.elts for name in assigned_names(item)}
    return set()


def assigned_aliases(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Attribute):
        chain = attribute_chain(node)
        return {".".join(chain)} if chain else set()
    if isinstance(node, (ast.Tuple, ast.List)):
        return {name for item in node.elts for name in assigned_aliases(item)}
    return assigned_names(node)


def assignment_bindings(target: ast.AST, value: ast.AST) -> list[tuple[str, ast.AST]]:
    """Pair destructured names with their corresponding values."""
    if (
        isinstance(target, (ast.Tuple, ast.List))
        and isinstance(value, (ast.Tuple, ast.List))
        and len(target.elts) == len(value.elts)
    ):
        pairs: list[tuple[str, ast.AST]] = []
        for child_target, child_value in zip(target.elts, value.elts):
            pairs.extend(assignment_bindings(child_target, child_value))
        return pairs
    return [(name, value) for name in assigned_aliases(target)]


def static_string(node: ast.AST) -> str | None:
    return static_text(node, {})


def static_text(node: ast.AST | None, constants: dict[str, str]) -> str | None:
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values = [static_text(item, constants) for item in node.elts]
        if any(value is None for value in values):
            return None
        return " ".join(value for value in values if value is not None)
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


def reflective_attribute(
    node: ast.AST,
    aliases: set[str],
    terminal: str,
    names: set[str],
) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and expression_chain(node.args[0], aliases, terminal)
        and static_string(node.args[1]) in names
    )


def simple_assignments(tree: ast.AST) -> dict[str, list[ast.AST]]:
    definitions: dict[str, list[ast.AST]] = defaultdict(list)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                for name, value in assignment_bindings(target, node.value):
                    definitions[name].append(value)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            names = assigned_aliases(node.target)
            if len(names) == 1:
                definitions[next(iter(names))].append(node.value)
    return dict(definitions)


def static_assignments(tree: ast.AST) -> dict[str, str]:
    """Resolve only unambiguous static assignments and always terminate.

    Multiple definitions are accepted only when every definition resolves to
    the same text. Cycles, branch-dependent values, and conflicting values
    remain unresolved, which makes process execution fail closed.
    """

    definitions = simple_assignments(tree)
    constants: dict[str, str] = {}
    unresolved = set(definitions)

    # Every successful pass removes at least one name. The explicit bound is a
    # second guarantee against a future regression reintroducing a toggle loop.
    for _ in range(len(definitions) + 1):
        progress = False
        for name in tuple(unresolved):
            values = [static_text(value, constants) for value in definitions[name]]
            if any(value is None for value in values):
                continue
            unresolved.remove(name)
            unique = {value for value in values if value is not None}
            if len(unique) == 1:
                constants[name] = unique.pop()
            progress = True
        if not progress:
            break
    return constants


def git_module_trees(root: Path) -> dict[str, str]:
    result = subprocess.run(
        ["git", "ls-tree", "HEAD:custom-addons"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return {}
    trees: dict[str, str] = {}
    for line in result.stdout.splitlines():
        match = re.fullmatch(r"\d+\s+tree\s+([0-9a-f]{40})\t(.+)", line)
        if match:
            trees[match.group(2)] = match.group(1)
    return trees


def reviewed_sql_policy(root: Path) -> tuple[set[str], set[str], set[str]]:
    """Return exact reviewed module trees and path-specific SQL exceptions."""

    baseline_path = root / "config" / "canonical-addon-baseline.json"
    try:
        payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return set(), set(), set()

    current_trees = git_module_trees(root)
    pinned = {
        module_name
        for module_name, expected_tree in payload.get("modules", {}).items()
        if isinstance(module_name, str)
        and isinstance(expected_tree, str)
        and current_trees.get(module_name) == expected_tree
    }

    exact_overrides: set[str] = set()
    exceptions: set[str] = set()
    for module_name, declaration in payload.get("strict_mission_overrides", {}).items():
        if not isinstance(module_name, str) or not isinstance(declaration, dict):
            continue
        current_tree = declaration.get("current_tree")
        if not isinstance(current_tree, str) or current_trees.get(module_name) != current_tree:
            continue
        exact_overrides.add(module_name)
        for entry in declaration.get("integration_boundary_exceptions", []):
            if not isinstance(entry, dict) or entry.get("kind") not in SQL_EXCEPTION_KINDS:
                continue
            relative = entry.get("path")
            if (
                isinstance(relative, str)
                and relative
                and ".." not in Path(relative).parts
            ):
                exceptions.add(f"{module_name}/{Path(relative).as_posix()}")
    return pinned, exact_overrides, exceptions


def expression_chain(node: ast.AST, aliases: set[str], terminal: str) -> bool:
    if isinstance(node, ast.Name):
        return node.id in aliases
    chain = attribute_chain(node)
    if not chain:
        return False
    if ".".join(chain) in aliases:
        return True
    if terminal == "cursor":
        if chain[-1] == "_cr" and chain[0] == "self":
            return True
        return chain[-1] == "cr" and ("env" in chain or len(chain) == 1)
    if terminal == "environment":
        return chain[-2:] in (["request", "env"], ["self", "env"])
    return False


def transitive_aliases(tree: ast.AST, *, terminal: str) -> set[str]:
    aliases = {"cr", "_cr"} if terminal == "cursor" else set()
    definitions = simple_assignments(tree)
    for _ in range(len(definitions) + 1):
        added = {
            name
            for name, values in definitions.items()
            if name not in aliases
            and values
            and all(expression_chain(value, aliases, terminal) for value in values)
        }
        if not added:
            break
        aliases.update(added)
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    calls = function_call_arguments(tree)
    for _ in range(len(functions) + 1):
        added: set[str] = set()
        for function in functions:
            name = function.name
            parameters = function_parameters(function)
            for call in calls.get(name, []):
                for index, parameter in enumerate(parameters):
                    positional_index = index
                    if isinstance(call.func, ast.Attribute) and parameters and parameters[0] in {"self", "cls"}:
                        positional_index -= 1
                    value = next((item.value for item in call.keywords if item.arg == parameter), None)
                    if value is None and 0 <= positional_index < len(call.args):
                        value = call.args[positional_index]
                    if value is not None and expression_chain(value, aliases, terminal):
                        added.add(parameter)
        added -= aliases
        if not added:
            break
        aliases.update(added)
    return aliases


def lexical_aliases(
    tree: ast.AST,
    *,
    terminal: str,
) -> dict[ast.AST | None, set[str]]:
    """Resolve aliases independently in each lexical function scope.

    File-wide alias inference is retained for helper argument propagation, but
    an unrelated assignment in another function must never erase a local
    cursor or environment alias.
    """

    enclosing = enclosing_functions(tree)
    scopes: list[ast.AST | None] = [None, *[
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]]
    result: dict[ast.AST | None, set[str]] = {}
    for scope in scopes:
        aliases = {"cr", "_cr"} if terminal == "cursor" else set()
        definitions: dict[str, list[ast.AST]] = defaultdict(list)
        for node in ast.walk(tree if scope is None else scope):
            if node is scope:
                continue
            if enclosing.get(node) is not scope:
                continue
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    for name, value in assignment_bindings(target, node.value):
                        definitions[name].append(value)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                names = assigned_aliases(node.target)
                if len(names) == 1:
                    definitions[next(iter(names))].append(node.value)
        for _ in range(len(definitions) + 1):
            added = {
                name
                for name, values in definitions.items()
                if name not in aliases
                and any(expression_chain(value, aliases, terminal) for value in values)
            }
            if not added:
                break
            aliases.update(added)
        result[scope] = aliases
    return result


def lexical_cursor_method_aliases(
    tree: ast.AST,
    cursor_aliases: set[str],
    scoped_cursor_aliases: dict[ast.AST | None, set[str]],
) -> dict[ast.AST | None, set[str]]:
    """Resolve names bound to a cursor's ``execute`` method per scope."""

    enclosing = enclosing_functions(tree)
    scopes: list[ast.AST | None] = [None, *[
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]]
    result: dict[ast.AST | None, set[str]] = {}
    for scope in scopes:
        definitions: dict[str, list[ast.AST]] = defaultdict(list)
        for node in ast.walk(tree if scope is None else scope):
            if node is scope or enclosing.get(node) is not scope:
                continue
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    for name, value in assignment_bindings(target, node.value):
                        definitions[name].append(value)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                names = assigned_aliases(node.target)
                if len(names) == 1:
                    definitions[next(iter(names))].append(node.value)

        methods: set[str] = set()
        effective_cursors = cursor_aliases | scoped_cursor_aliases.get(scope, set())
        for _ in range(len(definitions) + 1):
            added: set[str] = set()
            for name, values in definitions.items():
                if name in methods:
                    continue
                if any(
                    (
                        isinstance(value, ast.Attribute)
                        and value.attr in {"execute", "executemany"}
                        and expression_chain(value.value, effective_cursors, "cursor")
                    )
                    or reflective_attribute(
                        value,
                        effective_cursors,
                        "cursor",
                        {"execute", "executemany"},
                    )
                    or (
                        isinstance(value, ast.Call)
                        and value.args
                        and (
                            (
                                isinstance(value.args[0], ast.Attribute)
                                and value.args[0].attr in {"execute", "executemany"}
                                and expression_chain(
                                    value.args[0].value, effective_cursors, "cursor"
                                )
                            )
                            or reflective_attribute(
                                value.args[0],
                                effective_cursors,
                                "cursor",
                                {"execute", "executemany"},
                            )
                        )
                    )
                    or (isinstance(value, ast.Name) and value.id in methods)
                    for value in values
                ):
                    added.add(name)
            if not added:
                break
            methods.update(added)
        result[scope] = methods

    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    calls = function_call_arguments(tree)
    all_cursor_aliases = cursor_aliases | set().union(*scoped_cursor_aliases.values())
    for _ in range(len(functions) + 1):
        changed = False
        for function in functions:
            parameters = function_parameters(function)
            for call in calls.get(function.name, []):
                caller_methods = result.get(enclosing.get(call), set())
                for index, parameter in enumerate(parameters):
                    positional_index = index
                    if isinstance(call.func, ast.Attribute) and parameters and parameters[0] in {"self", "cls"}:
                        positional_index -= 1
                    value = next(
                        (item.value for item in call.keywords if item.arg == parameter),
                        None,
                    )
                    if value is None and 0 <= positional_index < len(call.args):
                        value = call.args[positional_index]
                    is_bound_execute = (
                        isinstance(value, ast.Attribute)
                        and value.attr in {"execute", "executemany"}
                        and expression_chain(value.value, all_cursor_aliases, "cursor")
                    ) or (
                        value is not None
                        and reflective_attribute(
                            value,
                            all_cursor_aliases,
                            "cursor",
                            {"execute", "executemany"},
                        )
                    ) or (
                        isinstance(value, ast.Name) and value.id in caller_methods
                    )
                    if is_bound_execute and parameter not in result[function]:
                        result[function].add(parameter)
                        changed = True
        if not changed:
            break
    return result


def is_cursor_execute(
    call: ast.Call,
    aliases: set[str],
    method_aliases: set[str],
) -> bool:
    return (
        (
            isinstance(call.func, ast.Attribute)
            and call.func.attr in {"execute", "executemany"}
            and expression_chain(call.func.value, aliases, "cursor")
        )
        or (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "__call__"
            and (
                (
                    isinstance(call.func.value, ast.Attribute)
                    and call.func.value.attr in {"execute", "executemany"}
                    and expression_chain(call.func.value.value, aliases, "cursor")
                )
                or reflective_attribute(
                    call.func.value,
                    aliases,
                    "cursor",
                    {"execute", "executemany"},
                )
                or ".".join(attribute_chain(call.func.value)) in method_aliases
            )
        )
        or (
            isinstance(call.func, (ast.Name, ast.Attribute))
            and ".".join(attribute_chain(call.func)) in method_aliases
        )
        or (
            isinstance(call.func, ast.Call)
            and reflective_attribute(
                call.func, aliases, "cursor", {"execute", "executemany"}
            )
        )
        or (
            isinstance(call.func, ast.Call)
            and call.func.args
            and (
                (
                    isinstance(call.func.args[0], ast.Attribute)
                    and call.func.args[0].attr in {"execute", "executemany"}
                    and expression_chain(call.func.args[0].value, aliases, "cursor")
                )
                or reflective_attribute(
                    call.func.args[0], aliases, "cursor", {"execute", "executemany"}
                )
                or ".".join(attribute_chain(call.func.args[0])) in method_aliases
            )
        )
    )


def container_values(node: ast.AST) -> list[ast.AST]:
    if isinstance(node, ast.Dict):
        return [*node.keys, *node.values]
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return list(node.elts)
    return []


def is_cursor_method_reference(node: ast.AST, aliases: set[str]) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr in {"execute", "executemany"}
        and expression_chain(node.value, aliases, "cursor")
    ) or reflective_attribute(
        node, aliases, "cursor", {"execute", "executemany"}
    )


def is_environment_selector_reference(node: ast.AST, aliases: set[str]) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "__getitem__"
        and expression_chain(node.value, aliases, "environment")
    ) or reflective_attribute(node, aliases, "environment", {"__getitem__"})


def operator_getitem_aliases(tree: ast.AST) -> tuple[set[str], set[str]]:
    modules: set[str] = set()
    functions: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "operator":
                    modules.add(alias.asname or "operator")
        elif isinstance(node, ast.ImportFrom) and node.module == "operator":
            for alias in node.names:
                if alias.name == "getitem":
                    functions.add(alias.asname or alias.name)
    definitions = simple_assignments(tree)
    for _ in range(len(definitions) + 1):
        added = {
            name
            for name, values in definitions.items()
            if name not in functions
            and any(
                (isinstance(value, ast.Name) and value.id in functions)
                or any(
                    attribute_chain(value)[-2:] == [module, "getitem"]
                    for module in modules
                )
                for value in values
            )
        }
        if not added:
            break
        functions.update(added)
    return modules, functions


def dynamic_model_selector(
    node: ast.AST,
    env_aliases: set[str],
    operator_modules: set[str] | None = None,
    operator_functions: set[str] | None = None,
    environment_selector_functions: set[str] | None = None,
) -> ast.AST | None:
    if isinstance(node, ast.Subscript) and expression_chain(
        node.value, env_aliases, "environment"
    ):
        return node.slice
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "__getitem__"
        and expression_chain(node.func.value, env_aliases, "environment")
        and node.args
    ):
        return node.args[0]
    if (
        isinstance(node, ast.Call)
        and node.args
        and isinstance(node.func, ast.Call)
        and isinstance(node.func.func, ast.Name)
        and node.func.func.id == "getattr"
        and len(node.func.args) >= 2
        and expression_chain(node.func.args[0], env_aliases, "environment")
        and static_string(node.func.args[1]) == "__getitem__"
    ):
        return node.args[0]
    if isinstance(node, ast.Call) and len(node.args) >= 2:
        chain = attribute_chain(node.func)
        is_operator_getitem = (
            isinstance(node.func, ast.Name)
            and node.func.id in (operator_functions or set())
        ) or (
            len(chain) == 2
            and chain[0] in (operator_modules or set())
            and chain[1] == "getitem"
        )
        if is_operator_getitem and expression_chain(
            node.args[0], env_aliases, "environment"
        ):
            return node.args[1]
    if (
        isinstance(node, ast.Call)
        and node.args
        and isinstance(node.func, (ast.Name, ast.Attribute))
        and ".".join(attribute_chain(node.func))
        in (environment_selector_functions or set())
    ):
        return node.args[0]
    return None


def lexical_environment_selector_aliases(
    tree: ast.AST,
    environment_aliases: set[str],
    scoped_environment_aliases: dict[ast.AST | None, set[str]],
) -> dict[ast.AST | None, set[str]]:
    """Resolve bound environment ``__getitem__`` callables per scope."""
    enclosing = enclosing_functions(tree)
    scopes: list[ast.AST | None] = [None, *[
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]]
    result: dict[ast.AST | None, set[str]] = {}
    for scope in scopes:
        definitions: dict[str, list[ast.AST]] = defaultdict(list)
        for node in ast.walk(tree if scope is None else scope):
            if node is scope or enclosing.get(node) is not scope:
                continue
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    for name, value in assignment_bindings(target, node.value):
                        definitions[name].append(value)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                for name in assigned_aliases(node.target):
                    definitions[name].append(node.value)
        effective_environments = environment_aliases | scoped_environment_aliases.get(scope, set())
        selectors: set[str] = set()
        for _ in range(len(definitions) + 1):
            added = {
                name
                for name, values in definitions.items()
                if name not in selectors
                and any(
                    (
                        isinstance(value, ast.Attribute)
                        and value.attr == "__getitem__"
                        and expression_chain(value.value, effective_environments, "environment")
                    )
                    or reflective_attribute(
                        value, effective_environments, "environment", {"__getitem__"}
                    )
                    or (
                        isinstance(value, ast.Call)
                        and value.args
                        and (
                            (
                                isinstance(value.args[0], ast.Attribute)
                                and value.args[0].attr == "__getitem__"
                                and expression_chain(value.args[0].value, effective_environments, "environment")
                            )
                            or reflective_attribute(value.args[0], effective_environments, "environment", {"__getitem__"})
                            or ".".join(attribute_chain(value.args[0])) in selectors
                        )
                    )
                    or (isinstance(value, ast.Name) and value.id in selectors)
                    for value in values
                )
            }
            if not added:
                break
            selectors.update(added)
        result[scope] = selectors

    functions = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    calls = function_call_arguments(tree)
    all_environments = environment_aliases | set().union(*scoped_environment_aliases.values())
    for _ in range(len(functions) + 1):
        changed = False
        for function in functions:
            parameters = function_parameters(function)
            for call in calls.get(function.name, []):
                caller_selectors = result.get(enclosing.get(call), set())
                for index, parameter in enumerate(parameters):
                    positional_index = index - (
                        1 if isinstance(call.func, ast.Attribute) and parameters and parameters[0] in {"self", "cls"} else 0
                    )
                    value = next(
                        (item.value for item in call.keywords if item.arg == parameter),
                        None,
                    )
                    if value is None and 0 <= positional_index < len(call.args):
                        value = call.args[positional_index]
                    is_selector = value is not None and (
                        (
                            isinstance(value, ast.Attribute)
                            and value.attr == "__getitem__"
                            and expression_chain(value.value, all_environments, "environment")
                        )
                        or reflective_attribute(
                            value, all_environments, "environment", {"__getitem__"}
                        )
                        or ".".join(attribute_chain(value)) in caller_selectors
                    )
                    if is_selector and parameter not in result[function]:
                        result[function].add(parameter)
                        changed = True
        if not changed:
            break
    return result


def is_acl_guarded_dynamic_browse(
    selector: ast.AST,
    function: ast.FunctionDef | ast.AsyncFunctionDef | None,
) -> bool:
    """Recognize a narrow dynamic read that preserves Odoo ACL enforcement."""

    if function is None:
        return False
    assignments = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        and node.value is selector
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    ]
    if len(assignments) != 1:
        return False
    model_name = assignments[0].targets[0].id

    def is_guarded_browse_value(value: ast.AST) -> bool:
        candidate = value
        if (
            isinstance(candidate, ast.Call)
            and isinstance(candidate.func, ast.Attribute)
            and candidate.func.attr == "exists"
        ):
            candidate = candidate.func.value
        return (
            isinstance(candidate, ast.Call)
            and isinstance(candidate.func, ast.Attribute)
            and isinstance(candidate.func.value, ast.Name)
            and candidate.func.value.id == model_name
            and candidate.func.attr == "browse"
        )

    browse_assignments = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and is_guarded_browse_value(node.value)
    ]
    if len(browse_assignments) != 1:
        return False
    record_name = browse_assignments[0].targets[0].id
    # Do not try to prove read-only behavior once the selected record escapes
    # through another local name.  All uses must remain visibly rooted at the
    # single guarded binding below.
    if any(
        isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr))
        and getattr(node, "value", None) is not None
        and any(
            isinstance(value, ast.Name)
            and isinstance(value.ctx, ast.Load)
            and value.id == record_name
            for value in ast.walk(node.value)
        )
        and node is not browse_assignments[0]
        for node in ast.walk(function)
    ):
        return False
    model_methods = {
        node.func.attr
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == model_name
    }
    if model_methods != {"browse"}:
        return False
    record_methods = {
        node.func.attr
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == record_name
    }
    if record_methods != {"check_access"}:
        return False
    if any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Call)
        and isinstance(node.func.func, ast.Name)
        and node.func.func.id == "getattr"
        and node.func.args
        and isinstance(node.func.args[0], ast.Name)
        and node.func.args[0].id == record_name
        for node in ast.walk(function)
    ):
        return False

    def passes_record_object(value: ast.AST) -> bool:
        if isinstance(value, ast.Name):
            return value.id == record_name
        # Attribute/subscript reads derive a field value; direct record method
        # calls are independently restricted to the ACL guard below.
        if isinstance(value, (ast.Attribute, ast.Subscript)):
            return False
        return any(passes_record_object(child) for child in ast.iter_child_nodes(value))

    if any(
        isinstance(node, ast.Call)
        and not (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == record_name
            and node.func.attr == "check_access"
        )
        and any(
            passes_record_object(value)
            for value in (
                *node.args,
                *(keyword.value for keyword in node.keywords),
            )
        )
        for node in ast.walk(function)
    ):
        return False
    if any(
        isinstance(node, ast.Attribute)
        and isinstance(node.ctx, (ast.Store, ast.Del))
        and isinstance(node.value, ast.Name)
        and node.value.id == record_name
        for node in ast.walk(function)
    ):
        return False
    if any(
        isinstance(node, ast.Subscript)
        and isinstance(node.ctx, (ast.Store, ast.Del))
        and isinstance(node.value, ast.Name)
        and node.value.id == record_name
        for node in ast.walk(function)
    ):
        return False
    if any(
        isinstance(node, (ast.Return, ast.Yield, ast.YieldFrom))
        and node.value is not None
        and passes_record_object(node.value)
        for node in ast.walk(function)
    ):
        return False

    # The guard must be an unconditional top-level statement after the browse.
    # Merely finding it somewhere in the function would accept unreachable or
    # caller-controlled checks and would not establish dominance.
    browse_statement = browse_assignments[0]
    try:
        browse_index = function.body.index(browse_statement)
    except ValueError:
        return False
    guard_indexes = [
        index
        for index, statement in enumerate(function.body)
        if isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Call)
        and isinstance(statement.value.func, ast.Attribute)
        and isinstance(statement.value.func.value, ast.Name)
        and statement.value.func.value.id == record_name
        and statement.value.func.attr == "check_access"
        and statement.value.args
        and static_string(statement.value.args[0]) == "read"
    ]
    if len(guard_indexes) != 1 or guard_indexes[0] <= browse_index:
        return False
    for statement in function.body[browse_index + 1 : guard_indexes[0]]:
        if any(
            isinstance(child, ast.Name)
            and child.id == record_name
            and isinstance(child.ctx, ast.Load)
            for child in ast.walk(statement)
        ):
            return False
    return True


def function_parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    return [
        argument.arg
        for argument in (
            *node.args.posonlyargs,
            *node.args.args,
            *node.args.kwonlyargs,
        )
    ]


def function_call_arguments(tree: ast.AST) -> dict[str, list[ast.Call]]:
    calls: dict[str, list[ast.Call]] = defaultdict(list)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        chain = attribute_chain(node.func)
        if chain:
            calls[chain[-1]].append(node)
    return dict(calls)


def static_model_wrapper_parameters(
    tree: ast.AST,
    env_aliases: set[str],
) -> set[tuple[ast.FunctionDef | ast.AsyncFunctionDef, str]]:
    """Permit a private wrapper only when all in-file callers use literals."""

    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    calls = function_call_arguments(tree)
    safe: set[tuple[ast.FunctionDef | ast.AsyncFunctionDef, str]] = set()
    route_aliases = route_decorator_aliases(tree)
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }

    for function in functions:
        name = function.name
        if not name.startswith("_"):
            continue
        if any(
            (attribute_chain(decorator) or [""])[-1] in route_aliases
            or (
                isinstance(decorator, ast.Call)
                and (attribute_chain(decorator.func) or [""])[-1] in route_aliases
            )
            for decorator in function.decorator_list
        ):
            continue
        callable_escapes = any(
            (
                isinstance(child, (ast.Name, ast.Attribute))
                and isinstance(child.ctx, ast.Load)
                and (attribute_chain(child) or [""])[-1] == name
                and not (
                    isinstance(parents.get(child), ast.Call)
                    and parents[child].func is child
                )
            )
            or (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "getattr"
                and len(child.args) >= 2
                and static_string(child.args[1]) == name
            )
            for child in ast.walk(tree)
        )
        if callable_escapes:
            continue
        parameters = function_parameters(function)
        candidates: set[str] = set()
        for child in ast.walk(function):
            selector = dynamic_model_selector(child, env_aliases)
            if isinstance(selector, ast.Name) and selector.id in parameters:
                candidates.add(selector.id)

        for parameter in candidates:
            observed = calls.get(name, [])
            if not observed:
                continue
            parameter_index = parameters.index(parameter)
            all_literal = True
            for call in observed:
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
                        all_literal = False
                        break
                    value = call.args[positional_index]
                if static_string(value) is None:
                    all_literal = False
                    break
            if all_literal:
                safe.add((function, parameter))
    return safe


def route_decorator_aliases(tree: ast.AST) -> set[str]:
    aliases = {"route"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "odoo.http":
            for imported in node.names:
                if imported.name == "route":
                    aliases.add(imported.asname or imported.name)
    definitions = simple_assignments(tree)
    for _ in range(len(definitions) + 1):
        added = {
            name
            for name, values in definitions.items()
            if name not in aliases
            and values
            and all((attribute_chain(value) or [""])[-1] in aliases for value in values)
        }
        if not added:
            break
        aliases.update(added)
    return aliases


def enclosing_functions(
    tree: ast.AST,
) -> dict[ast.AST, ast.FunctionDef | ast.AsyncFunctionDef]:
    result: dict[ast.AST, ast.FunctionDef | ast.AsyncFunctionDef] = {}

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.stack.append(node)
            for child in ast.iter_child_nodes(node):
                if self.stack:
                    result[child] = self.stack[-1]
                self.visit(child)
            self.stack.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self.stack.append(node)
            for child in ast.iter_child_nodes(node):
                if self.stack:
                    result[child] = self.stack[-1]
                self.visit(child)
            self.stack.pop()

        def generic_visit(self, node: ast.AST) -> None:
            for child in ast.iter_child_nodes(node):
                if self.stack:
                    result[child] = self.stack[-1]
                self.visit(child)

    Visitor().visit(tree)
    return result


def lexical_static_values(tree: ast.AST) -> set[str]:
    """Resolve static assignment values without merging unrelated scopes."""
    enclosing = enclosing_functions(tree)
    scopes: list[ast.AST | None] = [None, *[
        node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]]
    resolved_values: set[str] = set()
    resolved_by_scope: dict[ast.AST | None, dict[str, str]] = {}
    for scope in scopes:
        definitions: dict[str, list[ast.AST]] = defaultdict(list)
        for node in ast.walk(tree if scope is None else scope):
            if node is scope or enclosing.get(node) is not scope:
                continue
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    for name, value in assignment_bindings(target, node.value):
                        definitions[name].append(value)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                for name in assigned_aliases(node.target):
                    definitions[name].append(node.value)
        parent_scope = enclosing.get(scope) if scope is not None else None
        constants = dict(resolved_by_scope.get(parent_scope, {}))
        # A local binding shadows an inherited value even when the local value
        # cannot itself be resolved statically.
        for name in definitions:
            constants.pop(name, None)
        unresolved = set(definitions)
        for _ in range(len(definitions) + 1):
            progress = False
            for name in tuple(unresolved):
                values = [static_text(value, constants) for value in definitions[name]]
                if any(value is None for value in values):
                    continue
                unresolved.remove(name)
                unique = {value for value in values if value is not None}
                if len(unique) == 1:
                    constants[name] = unique.pop()
                progress = True
            if not progress:
                break
        resolved_values.update(constants.values())
        resolved_by_scope[scope] = constants
    return resolved_values


def imported_process_functions(tree: ast.AST) -> tuple[set[str], set[str], set[str]]:
    subprocess_modules = {"subprocess", "asyncio"}
    os_modules = {"os"}
    bare_functions: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {"subprocess", "asyncio"}:
                    subprocess_modules.add(alias.asname or alias.name)
                elif alias.name == "os":
                    os_modules.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module == "subprocess":
                for alias in node.names:
                    if alias.name == "*":
                        bare_functions.update(SUBPROCESS_FUNCTIONS)
                    elif alias.name in SUBPROCESS_FUNCTIONS:
                        bare_functions.add(alias.asname or alias.name)
            elif node.module == "asyncio":
                for alias in node.names:
                    if alias.name == "*":
                        bare_functions.update(ASYNCIO_PROCESS_FUNCTIONS)
                    elif alias.name in ASYNCIO_PROCESS_FUNCTIONS:
                        bare_functions.add(alias.asname or alias.name)
            elif node.module == "os":
                for alias in node.names:
                    if alias.name == "*":
                        bare_functions.update(OS_PROCESS_FUNCTIONS)
                    elif alias.name in OS_PROCESS_FUNCTIONS:
                        bare_functions.add(alias.asname or alias.name)
    definitions = simple_assignments(tree)
    for _ in range(len(definitions) + 1):
        added_subprocess: set[str] = set()
        added_os: set[str] = set()
        for name, values in definitions.items():
            if len(values) != 1 or not isinstance(values[0], ast.Name):
                continue
            if values[0].id in subprocess_modules:
                added_subprocess.add(name)
            if values[0].id in os_modules:
                added_os.add(name)
        added_subprocess -= subprocess_modules
        added_os -= os_modules
        if not added_subprocess and not added_os:
            break
        subprocess_modules.update(added_subprocess)
        os_modules.update(added_os)
    for _ in range(len(definitions) + 1):
        added = set()
        for name, values in definitions.items():
            if name in bare_functions or len(values) != 1:
                continue
            if is_process_reference(
                values[0], subprocess_modules, os_modules, bare_functions
            ):
                added.add(name)
        if not added:
            break
        bare_functions.update(added)

    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    calls = function_call_arguments(tree)
    for _ in range(len(functions) + 1):
        added: set[str] = set()
        for function in functions:
            parameters = function_parameters(function)
            positional = [*function.args.posonlyargs, *function.args.args]
            defaults = [None] * (len(positional) - len(function.args.defaults)) + list(function.args.defaults)
            default_by_name = {argument.arg: value for argument, value in zip(positional, defaults) if value is not None}
            default_by_name.update(
                {
                    argument.arg: value
                    for argument, value in zip(function.args.kwonlyargs, function.args.kw_defaults)
                    if value is not None
                }
            )
            for parameter, value in default_by_name.items():
                if is_process_reference(value, subprocess_modules, os_modules, bare_functions):
                    added.add(parameter)
            for call in calls.get(function.name, []):
                for index, parameter in enumerate(parameters):
                    positional_index = index
                    if isinstance(call.func, ast.Attribute) and parameters and parameters[0] in {"self", "cls"}:
                        positional_index -= 1
                    value = next((item.value for item in call.keywords if item.arg == parameter), None)
                    if value is None and 0 <= positional_index < len(call.args):
                        value = call.args[positional_index]
                    if value is not None and is_process_reference(value, subprocess_modules, os_modules, bare_functions):
                        added.add(parameter)
        added -= bare_functions
        if not added:
            break
        bare_functions.update(added)
    return subprocess_modules, os_modules, bare_functions


def lexical_process_aliases(
    tree: ast.AST,
    subprocess_modules: set[str],
    os_modules: set[str],
    bare_functions: set[str],
) -> dict[ast.AST | None, tuple[set[str], set[str], set[str]]]:
    """Resolve process modules and callables independently per lexical scope."""

    enclosing = enclosing_functions(tree)
    scopes: list[ast.AST | None] = [None, *[
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]]
    result: dict[ast.AST | None, tuple[set[str], set[str], set[str]]] = {}

    for scope in scopes:
        definitions: dict[str, list[ast.AST]] = defaultdict(list)
        for node in ast.walk(tree if scope is None else scope):
            if node is scope or enclosing.get(node) is not scope:
                continue
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    for name, value in assignment_bindings(target, node.value):
                        definitions[name].append(value)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                for name in assigned_aliases(node.target):
                    definitions[name].append(node.value)

        scoped_subprocess = set(subprocess_modules)
        scoped_os = set(os_modules)
        scoped_bare = set(bare_functions)
        for _ in range(len(definitions) + 1):
            changed = False
            for name, values in definitions.items():
                for value in values:
                    chain = attribute_chain(value)
                    if len(chain) == 1 and chain[0] in scoped_subprocess and name not in scoped_subprocess:
                        scoped_subprocess.add(name)
                        changed = True
                    if len(chain) == 1 and chain[0] in scoped_os and name not in scoped_os:
                        scoped_os.add(name)
                        changed = True
                    if is_process_reference(value, scoped_subprocess, scoped_os, scoped_bare) and name not in scoped_bare:
                        scoped_bare.add(name)
                        changed = True
            if not changed:
                break
        result[scope] = (scoped_subprocess, scoped_os, scoped_bare)
    return result


def is_process_reference(
    node: ast.AST,
    subprocess_modules: set[str],
    os_modules: set[str],
    bare_functions: set[str],
) -> bool:
    if (
        isinstance(node, ast.Call)
        and node.args
        and is_process_reference(
            node.args[0], subprocess_modules, os_modules, bare_functions
        )
    ):
        return True
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
    ):
        base = attribute_chain(node.args[0])
        name = static_string(node.args[1])
        return bool(base) and (
            (base[0] in subprocess_modules and name in (SUBPROCESS_FUNCTIONS | ASYNCIO_PROCESS_FUNCTIONS))
            or (base[0] in os_modules and name in OS_PROCESS_FUNCTIONS)
        )
    chain = attribute_chain(node)
    if len(chain) == 1:
        return chain[0] in bare_functions
    return bool(chain) and (
        (chain[0] in subprocess_modules and chain[-1] in (SUBPROCESS_FUNCTIONS | ASYNCIO_PROCESS_FUNCTIONS))
        or (chain[0] in os_modules and chain[-1] in OS_PROCESS_FUNCTIONS)
    )


def is_process_call(
    call: ast.Call,
    subprocess_modules: set[str],
    os_modules: set[str],
    bare_functions: set[str],
) -> bool:
    if is_process_reference(
        call.func, subprocess_modules, os_modules, bare_functions
    ):
        return True
    chain = attribute_chain(call.func)
    if not chain:
        return False
    if ".".join(chain) in bare_functions or chain[-1] in bare_functions:
        return True
    if len(chain) == 1:
        return chain[0] in bare_functions
    root, name = chain[0], chain[-1]
    return (root in subprocess_modules and name in (SUBPROCESS_FUNCTIONS | ASYNCIO_PROCESS_FUNCTIONS)) or (
        root in os_modules and name in OS_PROCESS_FUNCTIONS
    )


def process_command_node(call: ast.Call) -> ast.AST | None:
    chain = attribute_chain(call.func)
    function_name = chain[-1] if chain else ""
    command_index = 1 if function_name.startswith("spawn") else 0
    if len(call.args) > command_index:
        return call.args[command_index]
    return next(
        (
            keyword.value
            for keyword in call.keywords
            if keyword.arg in {"args", "command"}
        ),
        None,
    )


def odoo_sql_db_aliases(tree: ast.AST) -> tuple[set[str], set[str]]:
    modules = {"sql_db"}
    functions: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "odoo.sql_db":
                    modules.add(alias.asname or alias.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom) and node.module == "odoo.sql_db":
            for alias in node.names:
                functions.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "odoo":
            for alias in node.names:
                if alias.name == "sql_db":
                    modules.add(alias.asname or alias.name)
    definitions = simple_assignments(tree)
    for _ in range(len(definitions) + 1):
        added = {
            name
            for name, values in definitions.items()
            if len(values) == 1
            and isinstance(values[0], ast.Name)
            and values[0].id in modules
        } - modules
        if not added:
            break
        modules.update(added)
    return modules, functions


def python_findings(path: Path, *, allow_cursor_sql: bool) -> list[str]:
    findings: list[str] = []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        return [f"cannot parse Python source: {exc}"]

    constants = static_assignments(tree)
    cursor_names = transitive_aliases(tree, terminal="cursor")
    env_names = transitive_aliases(tree, terminal="environment")
    scoped_cursor_names = lexical_aliases(tree, terminal="cursor")
    scoped_env_names = lexical_aliases(tree, terminal="environment")
    scoped_env_selectors = lexical_environment_selector_aliases(
        tree, env_names, scoped_env_names
    )
    scoped_cursor_methods = lexical_cursor_method_aliases(
        tree, cursor_names, scoped_cursor_names
    )
    safe_wrappers = static_model_wrapper_parameters(tree, env_names)
    enclosing = enclosing_functions(tree)
    subprocess_modules, os_modules, bare_process = imported_process_functions(tree)
    scoped_process = lexical_process_aliases(
        tree, subprocess_modules, os_modules, bare_process
    )
    sql_db_modules, sql_db_functions = odoo_sql_db_aliases(tree)
    operator_modules, operator_functions = operator_getitem_aliases(tree)

    if any(DB_CREDENTIAL.search(value) for value in lexical_static_values(tree)) or any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and DB_CREDENTIAL.search(node.value)
        for node in ast.walk(tree)
    ):
        findings.append("Python source contains database credentials or PostgreSQL DSN")

    for imported in sorted(sql_db_functions):
        findings.append(f"Odoo sql_db helper import is prohibited: {imported}")

    for node in ast.walk(tree):
        scope = enclosing.get(node)
        effective_cursor_names = cursor_names | scoped_cursor_names.get(scope, set())
        effective_env_names = env_names | scoped_env_names.get(scope, set())
        effective_env_selectors = scoped_env_selectors.get(scope, set())
        effective_cursor_methods = scoped_cursor_methods.get(scope, set())
        effective_subprocess, effective_os, effective_process = scoped_process.get(
            scope, (subprocess_modules, os_modules, bare_process)
        )
        if is_process_reference(
            node, effective_subprocess, effective_os, effective_process
        ):
            findings.append(
                "process launcher capability references are prohibited in Odoo addons"
            )
        values = container_values(node)
        if any(
            is_cursor_method_reference(value, effective_cursor_names)
            or (isinstance(value, ast.Name) and value.id in effective_cursor_methods)
            for value in values
        ):
            findings.append(
                "cursor method capabilities stored in containers are prohibited"
            )
        if any(
            is_environment_selector_reference(value, effective_env_names)
            or (isinstance(value, ast.Name) and value.id in effective_env_selectors)
            for value in values
        ):
            findings.append(
                "environment selector capabilities stored in containers are prohibited"
            )
        if isinstance(node, ast.Call):
            chain = attribute_chain(node.func)
            if chain and (
                chain[-1] in ODOO_SQL_DB_HELPERS
                and (
                    chain[-1] in sql_db_functions
                    or any(part in sql_db_modules for part in chain)
                )
            ):
                findings.append(
                    "separate Odoo sql_db connection helper is prohibited: "
                    + ".".join(chain)
                )

            if is_cursor_execute(
                node, effective_cursor_names, effective_cursor_methods
            ) and not allow_cursor_sql:
                findings.append(
                    "undeclared Odoo cursor execution is prohibited: "
                    + ".".join(chain)
                )

            if is_process_call(node, effective_subprocess, effective_os, effective_process):
                command_nodes = [process_command_node(node)]
                command_nodes.extend(
                    keyword.value for keyword in node.keywords if keyword.arg == "executable"
                )
                current_function = enclosing.get(node)
                local_names = set(function_parameters(current_function)) if current_function is not None else set()
                if current_function is not None:
                    local_names.update(
                        child.id
                        for child in ast.walk(current_function)
                        if isinstance(child, ast.Name)
                        and isinstance(child.ctx, ast.Store)
                        and enclosing.get(child) is current_function
                    )
                for command_node in command_nodes:
                    shadowed_local = command_node is not None and any(
                        isinstance(child, ast.Name) and child.id in local_names
                        for child in ast.walk(command_node)
                    )
                    command_text = None if shadowed_local else static_text(command_node, constants)
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

        selector = dynamic_model_selector(
            node,
            effective_env_names,
            operator_modules,
            operator_functions,
            scoped_env_selectors.get(scope, set()),
        )
        if selector is None:
            continue
        current_function = enclosing.get(node)
        shadowed_selector = (
            isinstance(selector, ast.Name)
            and current_function is not None
            and (
                selector.id in function_parameters(current_function)
                or any(
                    selector.id in assigned_names(candidate)
                    and enclosing.get(candidate) is current_function
                    for candidate in ast.walk(current_function)
                    if isinstance(candidate, (ast.Name, ast.Tuple, ast.List))
                    and isinstance(getattr(candidate, "ctx", None), ast.Store)
                )
            )
        )
        if not shadowed_selector and static_text(selector, constants) is not None:
            continue
        if "tests" in path.parts:
            continue

        if is_acl_guarded_dynamic_browse(node, current_function):
            continue

        if (
            isinstance(selector, ast.Name)
            and current_function is not None
            and (current_function, selector.id) in safe_wrappers
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
        findings.append(
            "shell/config database credential or PostgreSQL DSN is prohibited"
        )
    return findings


def text_credential_findings(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return []
    if DB_CREDENTIAL.search(text):
        return ["addon text contains database credentials or PostgreSQL DSN"]
    return []


def meaningful_test_method(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Assert):
            if not (
                isinstance(child.test, ast.Constant) and child.test.value is True
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
            tree = ast.parse(
                test_path.read_text(encoding="utf-8"), filename=str(test_path)
            )
        except (OSError, UnicodeError, SyntaxError) as exc:
            findings.append(f"cannot parse bridge test {module_name}: {exc}")
            continue

        tokens.update(semantic_test_tokens(tree))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {
                chain[-1]
                for base in node.bases
                if (chain := attribute_chain(base))
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
                or relative.as_posix() in sql_exceptions
            )
            for finding in python_findings(path, allow_cursor_sql=allow_sql):
                findings.append(f"{display}: {finding}")
        else:
            for finding in text_credential_findings(path):
                findings.append(f"{display}: {finding}")
            if path.suffix.lower() in CONFIG_SUFFIXES or os.access(path, os.X_OK):
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
