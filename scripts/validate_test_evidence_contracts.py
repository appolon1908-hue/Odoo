#!/usr/bin/env python3
"""Validate the required browser, load, security, and migration evidence plans."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "tests/contracts/canonical-endpoints.json",
    "tests/security/negative-authorization-matrix.json",
    "tests/security/test_mission_contracts.py",
    "tests/migration/upgrade-matrix.json",
    "tests/browser/screen_pop.spec.js",
    "tests/load/contact_center_events.js",
)


def main() -> int:
    errors: list[str] = []
    for relative in REQUIRED_FILES:
        if not (ROOT / relative).is_file():
            errors.append(f"missing evidence contract: {relative}")

    try:
        security = json.loads(
            (ROOT / "tests/security/negative-authorization-matrix.json").read_text(encoding="utf-8")
        )
        if len(security.get("scenarios", [])) != 10:
            errors.append("negative authorization matrix must contain exactly ten mission scenarios")
        if any(item.get("expected") != "deny" for item in security.get("scenarios", [])):
            errors.append("every negative authorization scenario must deny")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"cannot load negative authorization matrix: {exc}")

    try:
        migration = json.loads(
            (ROOT / "tests/migration/upgrade-matrix.json").read_text(encoding="utf-8")
        )
        if len(migration.get("required_scenarios", [])) < 6:
            errors.append("migration matrix is incomplete")
        if migration.get("destructive_shortcuts_allowed") is not False:
            errors.append("migration matrix must prohibit destructive shortcuts")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(f"cannot load migration matrix: {exc}")

    for relative in ("tests/browser/screen_pop.spec.js", "tests/load/contact_center_events.js"):
        text = (ROOT / relative).read_text(encoding="utf-8") if (ROOT / relative).is_file() else ""
        for host in ("api.codestra.co", "65.109.65.169", "65.21.67.207", "37.27.128.39"):
            if host not in text:
                errors.append(f"{relative}: production-host refusal is missing for {host}")

    if errors:
        print("Test evidence contract validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(f"EVIDENCE_CONTRACT_FILES={len(REQUIRED_FILES)}")
    print("NEGATIVE_AUTHORIZATION_MATRIX=PASS")
    print("BROWSER_PRODUCTION_TARGET_GUARD=PASS")
    print("LOAD_PRODUCTION_TARGET_GUARD=PASS")
    print("TEST_EVIDENCE_SOURCE_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
