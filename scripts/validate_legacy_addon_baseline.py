#!/usr/bin/env python3
"""Verify that separately reviewed canonical addon subtrees remain byte-identical."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "config" / "canonical-addon-baseline.json"


def git_tree_sha(relative: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", f"HEAD:{relative.as_posix()}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def main() -> int:
    errors: list[str] = []
    try:
        payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR=cannot load canonical addon baseline: {exc}", file=sys.stderr)
        return 1

    if payload.get("schema_version") != 1:
        errors.append("baseline schema_version must be 1")
    if payload.get("source_commit") != "9674951f4b2c9c53f88412885ed5c96fcb0769cc":
        errors.append("canonical source commit drifted")
    modules = payload.get("modules")
    if not isinstance(modules, dict) or len(modules) != 32:
        errors.append("canonical baseline must contain exactly 32 modules")
        modules = {}

    for name, expected in sorted(modules.items()):
        if not isinstance(name, str) or not isinstance(expected, str) or len(expected) != 40:
            errors.append(f"invalid baseline entry for {name!r}")
            continue
        relative = Path("custom-addons") / name
        actual = git_tree_sha(relative)
        if actual != expected:
            errors.append(f"{name}: expected subtree {expected}, got {actual or 'MISSING'}")
        else:
            print(f"PINNED_CANONICAL_ADDON={name}:{actual}")

    if errors:
        print("Canonical addon baseline validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"PINNED_CANONICAL_ADDONS={len(modules)}")
    print("CANONICAL_ADDON_BASELINE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
