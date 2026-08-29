#!/usr/bin/env python3
"""Validate the basic structure of Odoo custom addon manifests."""

from __future__ import annotations

import ast
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ADDONS_DIR = ROOT / "custom-addons"
MODULE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
VERSION_RE = re.compile(r"^19\.0\.\d+\.\d+\.\d+$")
DEPENDENCY_RE = MODULE_NAME_RE
ALLOWED_LICENSES = {"AGPL-3", "LGPL-3", "OEEL-1", "OPL-1"}


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

    for key in ("name", "version", "license"):
        value = manifest.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"manifest key {key!r} must be a non-empty string")

    if not VERSION_RE.fullmatch(str(manifest.get("version", ""))):
        errors.append("manifest version must match Odoo 19 policy 19.0.x.y.z")
    if manifest.get("license") not in ALLOWED_LICENSES:
        errors.append(
            "manifest license must be one of " + ", ".join(sorted(ALLOWED_LICENSES))
        )

    depends = manifest.get("depends", [])
    if not isinstance(depends, list) or not all(
        isinstance(item, str) and DEPENDENCY_RE.fullmatch(item) for item in depends
    ):
        errors.append("manifest key 'depends' must contain canonical module names")
    elif len(depends) != len(set(depends)):
        errors.append("manifest key 'depends' contains duplicate module names")

    installable = manifest.get("installable", True)
    if not isinstance(installable, bool):
        errors.append("manifest key 'installable' must be a boolean")

    for section in ("data", "demo"):
        entries = manifest.get(section, [])
        if not isinstance(entries, list) or not all(isinstance(item, str) for item in entries):
            errors.append(f"manifest key {section!r} must be a list of paths")
            continue
        if len(entries) != len(set(entries)):
            errors.append(f"manifest key {section!r} contains duplicate declarations")
        for relative_name in entries:
            relative = Path(relative_name)
            if relative.is_absolute() or ".." in relative.parts:
                errors.append(f"unsafe {section} path: {relative_name}")
                continue
            if any(char in relative_name for char in "*?["):
                errors.append(f"wildcards are not allowed in {section}: {relative_name}")
                continue
            target = module_dir / relative
            if not target.is_file():
                errors.append(f"missing {section} file: {relative_name}")
                continue
            if target.suffix.lower() == ".xml":
                try:
                    ET.parse(target)
                except (ET.ParseError, OSError) as exc:
                    errors.append(f"invalid XML file {relative_name}: {exc}")

    assets = manifest.get("assets", {})
    if not isinstance(assets, dict):
        errors.append("manifest key 'assets' must be a dictionary")
    else:
        for bundle, declarations in assets.items():
            if not isinstance(bundle, str) or not isinstance(declarations, list):
                errors.append("asset bundles must map names to lists")
                continue
            normalized: list[str] = []
            for declaration in declarations:
                asset = declaration if isinstance(declaration, str) else (
                    declaration[-1]
                    if isinstance(declaration, tuple)
                    and declaration
                    and isinstance(declaration[-1], str)
                    else None
                )
                if asset is None:
                    errors.append(f"invalid asset declaration in {bundle!r}: {declaration!r}")
                    continue
                normalized.append(asset)
                prefix = f"{module_dir.name}/"
                if not asset.startswith(prefix):
                    errors.append(f"asset is outside module namespace: {asset}")
                    continue
                pattern = asset[len(prefix):]
                try:
                    matches = list(module_dir.glob(pattern))
                except ValueError as exc:
                    errors.append(f"invalid asset wildcard pattern {asset}: {exc}")
                    continue
                if not matches or any(not match.is_file() for match in matches):
                    errors.append(f"referenced asset has no file match: {asset}")
            if len(normalized) != len(set(normalized)):
                errors.append(f"asset bundle {bundle!r} contains duplicate declarations")

    return errors


def main() -> int:
    if not ADDONS_DIR.is_dir():
        print(f"ERROR: missing addon directory: {ADDONS_DIR}", file=sys.stderr)
        return 1

    module_dirs = sorted(
        path
        for path in ADDONS_DIR.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    )
    if not module_dirs:
        print("No Odoo custom modules are present yet; scaffold validation passed.")
        return 0

    failures = 0
    for module_dir in module_dirs:
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

    print(f"Manifest validation passed for {len(module_dirs)} module(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
