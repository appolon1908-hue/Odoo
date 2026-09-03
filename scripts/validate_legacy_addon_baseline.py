#!/usr/bin/env python3
"""Verify immutable canonical add-ons and explicitly reviewed strict overrides."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "config" / "canonical-addon-baseline.json"
CANONICAL_SOURCE_COMMIT = "9674951f4b2c9c53f88412885ed5c96fcb0769cc"
CANONICAL_SOURCE_PULL_REQUEST = 9
CANONICAL_MODULE_COUNT = 32
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
MODULE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def git_tree_sha(relative: Path) -> str | None:
    treeish = os.environ.get("ODOO_VALIDATION_TREEISH", "HEAD")
    result = subprocess.run(
        ["git", "rev-parse", f"{treeish}:{relative.as_posix()}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def is_sha(value: Any) -> bool:
    return isinstance(value, str) and SHA_RE.fullmatch(value) is not None


def validate_module_name(name: Any, errors: list[str]) -> bool:
    if not isinstance(name, str) or MODULE_RE.fullmatch(name) is None:
        errors.append(f"invalid canonical module name: {name!r}")
        return False
    return True


def main() -> int:
    errors: list[str] = []
    try:
        payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR=cannot load canonical addon baseline: {exc}", file=sys.stderr)
        return 1

    if payload.get("schema_version") != 2:
        errors.append("baseline schema_version must be 2")
    if payload.get("source_commit") != CANONICAL_SOURCE_COMMIT:
        errors.append("canonical source commit drifted")
    if payload.get("source_pull_request") != CANONICAL_SOURCE_PULL_REQUEST:
        errors.append("canonical source pull request drifted")
    if payload.get("module_count") != CANONICAL_MODULE_COUNT:
        errors.append(
            f"canonical module_count must be {CANONICAL_MODULE_COUNT}"
        )

    modules = payload.get("modules")
    if not isinstance(modules, dict):
        errors.append("baseline modules must be an object")
        modules = {}

    overrides = payload.get("strict_mission_overrides")
    if not isinstance(overrides, dict):
        errors.append("strict_mission_overrides must be an object")
        overrides = {}

    overlap = set(modules).intersection(overrides)
    if overlap:
        errors.append(
            "modules cannot be both pinned and strict overrides: "
            + ", ".join(sorted(overlap))
        )

    registry_count = len(modules) + len(overrides)
    if registry_count != CANONICAL_MODULE_COUNT:
        errors.append(
            "canonical registry must contain exactly "
            f"{CANONICAL_MODULE_COUNT} modules; got {registry_count}"
        )

    for name, expected in sorted(modules.items()):
        if not validate_module_name(name, errors):
            continue
        if not is_sha(expected):
            errors.append(f"invalid pinned tree SHA for {name!r}")
            continue
        relative = Path("custom-addons") / name
        actual = git_tree_sha(relative)
        if actual != expected:
            errors.append(
                f"{name}: expected pinned subtree {expected}, "
                f"got {actual or 'MISSING'}"
            )
        else:
            print(f"PINNED_CANONICAL_ADDON={name}:{actual}")

    for name, declaration in sorted(overrides.items()):
        if not validate_module_name(name, errors):
            continue
        if not isinstance(declaration, dict):
            errors.append(f"strict override for {name!r} must be an object")
            continue

        base_tree = declaration.get("base_tree")
        current_tree = declaration.get("current_tree")
        reason = declaration.get("reason")
        pull_request = declaration.get("pull_request")

        if not is_sha(base_tree):
            errors.append(f"strict override {name!r} has invalid base_tree")
        if not is_sha(current_tree):
            errors.append(f"strict override {name!r} has invalid current_tree")
        if is_sha(base_tree) and is_sha(current_tree) and base_tree == current_tree:
            errors.append(
                f"strict override {name!r} must differ from its canonical base tree"
            )
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"strict override {name!r} requires a reason")
        if (
            not isinstance(pull_request, int)
            or isinstance(pull_request, bool)
            or pull_request <= 0
        ):
            errors.append(
                f"strict override {name!r} requires a positive pull_request number"
            )

        relative = Path("custom-addons") / name
        actual = git_tree_sha(relative)
        if is_sha(current_tree) and actual != current_tree:
            errors.append(
                f"{name}: expected strict-review subtree {current_tree}, "
                f"got {actual or 'MISSING'}"
            )
        elif actual:
            print(
                "STRICT_MISSION_OVERRIDE="
                f"{name}:{actual}:PR-{pull_request}"
            )

    if errors:
        print("Canonical addon baseline validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"PINNED_CANONICAL_ADDONS={len(modules)}")
    print(f"STRICT_MISSION_OVERRIDES={len(overrides)}")
    print(f"CANONICAL_ADDON_REGISTRY={registry_count}")
    print("CANONICAL_ADDON_BASELINE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
