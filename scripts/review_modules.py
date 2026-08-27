#!/usr/bin/env python3
"""Fail-closed review for new modules and immutable verification for audited modules."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDONS_DIR = ROOT / "custom-addons"
BASELINE = ROOT / "config" / "canonical-addon-baseline.json"
MODULE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
VERSION_RE = re.compile(r"^19\.0\.\d+\.\d+\.\d+$")
ALLOWED_LICENSES = {"LGPL-3", "AGPL-3", "OEEL-1", "OPL-1"}
FORBIDDEN_PATTERNS = {
    "hardcoded password assignment": re.compile(r"(?i)\b(?:password|passwd|pwd)\s*[:=]\s*['\"][^'\"]+['\"]"),
    "external PostgreSQL client": re.compile(r"(?m)^\s*(?:from|import)\s+(?:psycopg|psycopg2|asyncpg|sqlalchemy)\b"),
    "direct PostgreSQL URL": re.compile(r"(?i)postgres(?:ql)?://"),
    "private key material": re.compile(r"-----BEGIN .*PRIVATE KEY-----"),
}


def load_manifest(path: Path) -> dict:
    value = ast.literal_eval(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("manifest must be a Python dictionary")
    return value


def load_baseline() -> dict[str, str]:
    try:
        payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    modules = payload.get("modules", {})
    return modules if isinstance(modules, dict) else {}


def git_tree_sha(module_dir: Path) -> str | None:
    relative = module_dir.relative_to(ROOT)
    result = subprocess.run(
        ["git", "rev-parse", f"HEAD:{relative.as_posix()}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def asset_paths(manifest: dict) -> list[str]:
    result: list[str] = []
    assets = manifest.get("assets", {})
    if not isinstance(assets, dict):
        return result
    for entries in assets.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, str):
                result.append(entry)
            elif isinstance(entry, tuple) and entry and isinstance(entry[-1], str):
                result.append(entry[-1])
    return result


def validate_xml(path: Path, errors: list[str]) -> None:
    try:
        ET.parse(path)
    except (ET.ParseError, OSError) as exc:
        errors.append(f"{path.relative_to(ROOT)}: invalid XML: {exc}")


def validate_manifest_paths(module_dir: Path, manifest: dict, errors: list[str]) -> None:
    for section in ("data", "demo"):
        entries = manifest.get(section, [])
        if not isinstance(entries, list) or not all(isinstance(item, str) for item in entries):
            errors.append(f"manifest {section!r} must be a list of paths")
            continue
        for relative_name in entries:
            relative = Path(relative_name)
            if relative.is_absolute() or ".." in relative.parts:
                errors.append(f"unsafe manifest path: {relative_name}")
                continue
            matches = list(module_dir.glob(relative_name)) if any(char in relative_name for char in "*?[") else [module_dir / relative]
            if not matches or any(not target.is_file() for target in matches):
                errors.append(f"manifest path does not exist: {relative_name}")
                continue
            for target in matches:
                if target.suffix.lower() == ".xml":
                    validate_xml(target, errors)

    for declared in asset_paths(manifest):
        prefix = f"{module_dir.name}/"
        if not declared.startswith(prefix):
            errors.append(f"asset is outside module namespace: {declared}")
            continue
        if not list(module_dir.glob(declared[len(prefix):])):
            errors.append(f"asset path has no match: {declared}")


def review_module(module_dir: Path, baseline: dict[str, str]) -> tuple[list[str], list[str], str]:
    errors: list[str] = []
    warnings: list[str] = []
    pinned = baseline.get(module_dir.name) == git_tree_sha(module_dir)
    mode = "PINNED_CANONICAL" if pinned else "STRICT_MISSION"

    if not MODULE_RE.fullmatch(module_dir.name):
        errors.append("module directory name is not canonical")
    if not (module_dir / "__init__.py").is_file():
        errors.append("missing __init__.py")

    try:
        manifest = load_manifest(module_dir / "__manifest__.py")
    except (OSError, SyntaxError, ValueError) as exc:
        return [f"cannot parse manifest: {exc}"], warnings, mode

    required = ("name", "version", "license", "depends") if pinned else ("name", "summary", "version", "license", "depends")
    for key in required:
        if key not in manifest:
            errors.append(f"manifest missing {key!r}")
    if not isinstance(manifest.get("version"), str) or not VERSION_RE.fullmatch(manifest.get("version", "")):
        errors.append("manifest version must match 19.0.x.y.z")
    if manifest.get("license") not in ALLOWED_LICENSES:
        errors.append(f"unsupported or missing license: {manifest.get('license')!r}")
    depends = manifest.get("depends")
    if not isinstance(depends, list) or not depends or not all(isinstance(item, str) and item for item in depends):
        errors.append("manifest depends must be a non-empty list of module names")
    if manifest.get("installable") is not True:
        errors.append("manifest installable must be True")

    validate_manifest_paths(module_dir, manifest, errors)
    if pinned:
        return errors, warnings, mode

    if not (module_dir / "README.md").is_file():
        warnings.append("missing module README.md")
    if not isinstance(manifest.get("application", False), bool):
        errors.append("manifest application must be boolean")
    if manifest.get("post_init_hook"):
        errors.append("post_init_hook requires a separately pinned and reviewed subtree")

    tests_dir = module_dir / "tests"
    if not tests_dir.is_dir():
        warnings.append("no Odoo tests directory")
    else:
        init_path = tests_dir / "__init__.py"
        if not init_path.is_file():
            errors.append("tests directory is missing __init__.py")
            init_text = ""
        else:
            init_text = init_path.read_text(encoding="utf-8")
        test_files = sorted(tests_dir.glob("test_*.py"))
        if not test_files:
            errors.append("tests directory contains no test_*.py files")
        for test_file in test_files:
            if test_file.stem not in init_text:
                errors.append(f"tests/__init__.py does not import {test_file.stem}")

    if list((module_dir / "models").glob("*.py")) and not (module_dir / "security" / "ir.model.access.csv").is_file():
        warnings.append("module defines model files but has no ir.model.access.csv")

    for path in sorted(module_dir.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".woff", ".woff2"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        for label, pattern in FORBIDDEN_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"{path.relative_to(module_dir)} contains {label}")

    return errors, warnings, mode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review every custom Odoo module.")
    parser.add_argument("--strict", action="store_true", help="Treat mission-module warnings as failures.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    baseline = load_baseline()
    module_dirs = sorted(path.parent for path in ADDONS_DIR.glob("*/__manifest__.py"))
    if not module_dirs:
        print("ERROR: no custom Odoo modules are present", file=sys.stderr)
        return 1

    total_errors = total_warnings = pinned_count = 0
    for module_dir in module_dirs:
        errors, warnings, mode = review_module(module_dir, baseline)
        total_errors += len(errors)
        total_warnings += len(warnings)
        pinned_count += int(mode == "PINNED_CANONICAL")
        print(f"MODULE={module_dir.name}")
        print(f"MODULE_REVIEW_MODE={mode}")
        print(f"MODULE_ERRORS={len(errors)}")
        print(f"MODULE_WARNINGS={len(warnings)}")
        for warning in warnings:
            print(f"WARNING={module_dir.name}: {warning}")
        for error in errors:
            print(f"ERROR={module_dir.name}: {error}", file=sys.stderr)

    print(f"MODULES_REVIEWED={len(module_dirs)}")
    print(f"PINNED_CANONICAL_MODULES={pinned_count}")
    print(f"MODULE_REVIEW_ERRORS={total_errors}")
    print(f"MODULE_REVIEW_WARNINGS={total_warnings}")
    if total_errors or (args.strict and total_warnings):
        return 1
    print(f"MODULE_REVIEW_STRICT={'YES' if args.strict else 'NO'}")
    print("MODULE_REVIEW=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
