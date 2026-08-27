#!/usr/bin/env python3
"""Static, fail-closed review for every custom Odoo module in the repository."""

from __future__ import annotations

import argparse
import ast
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADDONS_DIR = ROOT / "custom-addons"
MODULE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
VERSION_RE = re.compile(r"^19\.0\.\d+\.\d+\.\d+$")
ALLOWED_LICENSES = {"LGPL-3", "AGPL-3", "OEEL-1", "OPL-1"}
FORBIDDEN_PATTERNS = {
    "hardcoded password assignment": re.compile(
        r"(?i)\b(?:password|passwd|pwd)\s*[:=]\s*['\"][^'\"]+['\"]"
    ),
    "external PostgreSQL client": re.compile(
        r"(?m)^\s*(?:from|import)\s+(?:psycopg|psycopg2|asyncpg|sqlalchemy)\b"
    ),
    "direct PostgreSQL URL": re.compile(r"(?i)postgres(?:ql)?://"),
    "private key material": re.compile(r"-----BEGIN .*PRIVATE KEY-----"),
}


def load_manifest(path: Path) -> dict:
    value = ast.literal_eval(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("manifest must be a Python dictionary")
    return value


def asset_paths(manifest: dict) -> list[str]:
    paths: list[str] = []
    assets = manifest.get("assets", {})
    if not isinstance(assets, dict):
        return paths
    for entries in assets.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, str):
                paths.append(entry)
            elif isinstance(entry, tuple) and entry and isinstance(entry[-1], str):
                paths.append(entry[-1])
    return paths


def validate_xml(path: Path, errors: list[str]) -> None:
    try:
        ET.parse(path)
    except (ET.ParseError, OSError) as exc:
        errors.append(f"{path.relative_to(ROOT)}: invalid XML: {exc}")


def review_module(module_dir: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    manifest_path = module_dir / "__manifest__.py"

    if not MODULE_RE.fullmatch(module_dir.name):
        errors.append("module directory name is not canonical")
    if not (module_dir / "__init__.py").is_file():
        errors.append("missing __init__.py")
    if not (module_dir / "README.md").is_file():
        warnings.append("missing module README.md")

    try:
        manifest = load_manifest(manifest_path)
    except (OSError, SyntaxError, ValueError) as exc:
        return [f"cannot parse manifest: {exc}"], warnings

    for key in ("name", "summary", "version", "license", "depends"):
        if key not in manifest:
            errors.append(f"manifest missing {key!r}")

    version = manifest.get("version")
    if not isinstance(version, str) or not VERSION_RE.fullmatch(version):
        errors.append("manifest version must match 19.0.x.y.z")

    license_name = manifest.get("license")
    if license_name not in ALLOWED_LICENSES:
        errors.append(f"unsupported or missing license: {license_name!r}")

    depends = manifest.get("depends")
    if (
        not isinstance(depends, list)
        or not depends
        or not all(isinstance(item, str) and item for item in depends)
    ):
        errors.append("manifest depends must be a non-empty list of module names")

    if manifest.get("installable") is not True:
        errors.append("manifest installable must be True")
    if not isinstance(manifest.get("application", False), bool):
        errors.append("manifest application must be boolean")
    if manifest.get("post_init_hook"):
        errors.append(
            "post_init_hook is prohibited for administrator/bootstrap side effects"
        )

    referenced_paths: list[str] = []
    for section in ("data", "demo"):
        entries = manifest.get(section, [])
        if not isinstance(entries, list) or not all(
            isinstance(item, str) for item in entries
        ):
            errors.append(f"manifest {section!r} must be a list of paths")
            continue
        referenced_paths.extend(entries)

    for relative_name in referenced_paths:
        relative = Path(relative_name)
        if relative.is_absolute() or ".." in relative.parts:
            errors.append(f"unsafe manifest path: {relative_name}")
            continue
        target = module_dir / relative
        if not target.is_file():
            errors.append(f"manifest path does not exist: {relative_name}")
        elif target.suffix.lower() == ".xml":
            validate_xml(target, errors)

    for declared_asset in asset_paths(manifest):
        prefix = f"{module_dir.name}/"
        if not declared_asset.startswith(prefix):
            errors.append(f"asset is outside module namespace: {declared_asset}")
            continue
        relative_pattern = declared_asset[len(prefix):]
        matches = list(module_dir.glob(relative_pattern))
        if not matches:
            errors.append(f"asset path has no match: {declared_asset}")

    tests_dir = module_dir / "tests"
    if not tests_dir.is_dir():
        warnings.append("no Odoo tests directory")
    else:
        if not (tests_dir / "__init__.py").is_file():
            errors.append("tests directory is missing __init__.py")
        test_files = sorted(tests_dir.glob("test_*.py"))
        if not test_files:
            errors.append("tests directory contains no test_*.py files")
        init_text = (
            (tests_dir / "__init__.py").read_text(encoding="utf-8")
            if (tests_dir / "__init__.py").is_file()
            else ""
        )
        for test_file in test_files:
            module_name = test_file.stem
            if module_name not in init_text:
                errors.append(
                    f"tests/__init__.py does not import {module_name}"
                )

    model_files = list((module_dir / "models").glob("*.py"))
    if model_files and not (
        module_dir / "security" / "ir.model.access.csv"
    ).is_file():
        warnings.append(
            "module defines model files but has no ir.model.access.csv; "
            "confirm all models are abstract/transient or otherwise protected"
        )

    for path in sorted(module_dir.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".woff", ".woff2"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        for label, pattern in FORBIDDEN_PATTERNS.items():
            if pattern.search(text):
                errors.append(
                    f"{path.relative_to(module_dir)} contains {label}"
                )

    return errors, warnings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Review every custom Odoo module."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat review warnings as blocking failures.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not ADDONS_DIR.is_dir():
        print("ERROR: custom-addons directory is missing", file=sys.stderr)
        return 1

    module_dirs = sorted(
        path.parent
        for path in ADDONS_DIR.glob("*/__manifest__.py")
    )
    if not module_dirs:
        print("ERROR: no custom Odoo modules are present", file=sys.stderr)
        return 1

    total_errors = 0
    total_warnings = 0
    for module_dir in module_dirs:
        errors, warnings = review_module(module_dir)
        total_errors += len(errors)
        total_warnings += len(warnings)

        print(f"MODULE={module_dir.name}")
        print(f"MODULE_ERRORS={len(errors)}")
        print(f"MODULE_WARNINGS={len(warnings)}")
        for warning in warnings:
            print(f"WARNING={module_dir.name}: {warning}")
        for error in errors:
            print(f"ERROR={module_dir.name}: {error}", file=sys.stderr)

    print(f"MODULES_REVIEWED={len(module_dirs)}")
    print(f"MODULE_REVIEW_ERRORS={total_errors}")
    print(f"MODULE_REVIEW_WARNINGS={total_warnings}")

    if total_errors or (args.strict and total_warnings):
        if args.strict and total_warnings:
            print(
                "ERROR=strict module review rejects warnings",
                file=sys.stderr,
            )
        return 1

    print(f"MODULE_REVIEW_STRICT={'YES' if args.strict else 'NO'}")
    print("MODULE_REVIEW=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
