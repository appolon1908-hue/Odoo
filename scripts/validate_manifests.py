#!/usr/bin/env python3
"""Validate the basic structure of Odoo custom addon manifests."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ADDONS_DIR = ROOT / "custom-addons"
MODULE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = ast.literal_eval(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError) as exc:
        raise ValueError(f"cannot parse manifest: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("manifest must be a Python dictionary literal")
    return value


def validate_module(module_dir: Path) -> list[str]:
    errors: list[str] = []
    manifest_path = module_dir / "__manifest__.py"

    if not MODULE_NAME_RE.fullmatch(module_dir.name):
        errors.append("directory name must match ^[a-z][a-z0-9_]*$")
    if not (module_dir / "__init__.py").is_file():
        errors.append("missing __init__.py")

    try:
        manifest = load_manifest(manifest_path)
    except ValueError as exc:
        return [str(exc)]

    for key in ("name", "version"):
        value = manifest.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"manifest key {key!r} must be a non-empty string")

    depends = manifest.get("depends", [])
    if not isinstance(depends, list) or not all(
        isinstance(item, str) and item.strip() for item in depends
    ):
        errors.append("manifest key 'depends' must be a list of module names")

    installable = manifest.get("installable", True)
    if not isinstance(installable, bool):
        errors.append("manifest key 'installable' must be a boolean")

    for section in ("data", "demo"):
        entries = manifest.get(section, [])
        if not isinstance(entries, list) or not all(isinstance(item, str) for item in entries):
            errors.append(f"manifest key {section!r} must be a list of paths")
            continue
        for relative_name in entries:
            relative = Path(relative_name)
            if relative.is_absolute() or ".." in relative.parts:
                errors.append(f"unsafe {section} path: {relative_name}")
                continue
            if any(char in relative_name for char in "*?["):
                continue
            if not (module_dir / relative).is_file():
                errors.append(f"missing {section} file: {relative_name}")

    return errors


def main() -> int:
    if not ADDONS_DIR.is_dir():
        print(f"ERROR: missing addon directory: {ADDONS_DIR}", file=sys.stderr)
        return 1

    manifests = sorted(ADDONS_DIR.glob("*/__manifest__.py"))
    if not manifests:
        print("No Odoo custom modules are present yet; scaffold validation passed.")
        return 0

    failures = 0
    for manifest_path in manifests:
        module_dir = manifest_path.parent
        module_errors = validate_module(module_dir)
        if module_errors:
            failures += 1
            print(f"ERROR: {module_dir.name}", file=sys.stderr)
            for error in module_errors:
                print(f"  - {error}", file=sys.stderr)
        else:
            print(f"PASS: {module_dir.name}")

    if failures:
        print(f"Manifest validation failed for {failures} module(s).", file=sys.stderr)
        return 1

    print(f"Manifest validation passed for {len(manifests)} module(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
