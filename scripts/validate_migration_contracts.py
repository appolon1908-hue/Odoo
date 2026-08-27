#!/usr/bin/env python3
"""Validate additive migration policy for every new model-owning mission module."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDONS = ROOT / "custom-addons"
SCHEMA_MODULES = {
    "codestra_case_management",
    "codestra_cc_workforce",
    "codestra_agent_onboarding",
    "codestra_training_academy",
    "codestra_client_operations",
    "codestra_revenue_assurance",
    "codestra_data_quality",
    "codestra_ai_agent_assistant",
}
DESTRUCTIVE = re.compile(
    r"(?is)\b(?:drop\s+table|truncate\s+table|delete\s+from|alter\s+table\b.{0,200}\bdrop\s+column)\b"
)


def main() -> int:
    errors: list[str] = []
    for name in sorted(SCHEMA_MODULES):
        migration_dir = ADDONS / name / "migrations"
        policy = migration_dir / "README.md"
        if not policy.is_file():
            errors.append(f"{name}: migration policy is missing")
            continue
        text = policy.read_text(encoding="utf-8").lower()
        for phrase in ("restartable", "idempotent", "no destructive", "rollback"):
            if phrase not in text:
                errors.append(f"{name}: migration policy is missing {phrase!r}")
        for path in sorted(migration_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".py", ".sql"}:
                continue
            source = path.read_text(encoding="utf-8")
            if DESTRUCTIVE.search(source):
                errors.append(f"{path.relative_to(ROOT)}: destructive migration operation is prohibited")

    if errors:
        print("Migration contract validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(f"MISSION_MIGRATION_POLICIES={len(SCHEMA_MODULES)}")
    print("DESTRUCTIVE_MIGRATION_OPERATIONS=0")
    print("MISSION_MIGRATION_SOURCE_GATE=PASS")
    print("RESTORE_REHEARSAL_GATE=BLOCKED_RUNTIME_EVIDENCE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
