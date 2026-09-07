#!/usr/bin/env python3
"""Fail CI when the campaign authority matrix drifts from implemented groups."""

from __future__ import annotations

import ast
import csv
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX_PATH = ROOT / "docs/authority/odoo_campaign_access_control_matrix.csv"
GROUPS_PATH = (
    ROOT / "custom-addons/codestra_cc_security/security/groups.xml"
)
MEMBERSHIP_MODEL_PATH = (
    ROOT / "custom-addons/codestra_cc_security/models/campaign_security.py"
)

REQUIRED_COLUMNS = {
    "role_key",
    "stable_odoo_group",
    "status",
}
MATRIX_ROLE_TO_CODE_ROLE = {
    "agent": "agent",
    "senior_agent": "senior_agent",
    "supervisor": "supervisor",
    "qa_analyst": "qa",
    "wfm_analyst": "workforce",
    "compliance_officer": "compliance",
    "campaign_config_manager": "configuration_manager",
    "auditor": "auditor",
}
ADMIN_ROLE_GROUPS = {
    "global_cc_admin": "codestra_cc_security.group_cc_global_administrator",
    "technical_admin": "codestra_cc_security.group_cc_technical_administrator",
}
EXPECTED_ROLE_KEYS = set(MATRIX_ROLE_TO_CODE_ROLE) | set(ADMIN_ROLE_GROUPS)
VALID_STATUSES = {"MISSING", "PARTIAL", "PASS"}


def fail(errors: list[str]) -> int:
    for error in errors:
        print(f"campaign authority matrix: ERROR: {error}", file=sys.stderr)
    return 1


def load_role_group_xmlids(path: Path) -> dict[str, str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "ROLE_GROUP_XMLIDS"
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            if not isinstance(value, dict):
                raise ValueError("ROLE_GROUP_XMLIDS is not a dictionary")
            return value
    raise ValueError("ROLE_GROUP_XMLIDS assignment not found")


def load_defined_group_xmlids(path: Path) -> set[str]:
    root = ET.parse(path).getroot()
    return {
        f"codestra_cc_security.{record.attrib['id']}"
        for record in root.findall("record")
        if record.attrib.get("model") == "res.groups"
        and record.attrib.get("id")
    }


def main() -> int:
    errors: list[str] = []
    for path in (MATRIX_PATH, GROUPS_PATH, MEMBERSHIP_MODEL_PATH):
        if not path.is_file():
            errors.append(f"required source is missing: {path.relative_to(ROOT)}")
    if errors:
        return fail(errors)

    try:
        role_group_xmlids = load_role_group_xmlids(MEMBERSHIP_MODEL_PATH)
        defined_group_xmlids = load_defined_group_xmlids(GROUPS_PATH)
    except (OSError, SyntaxError, ValueError, ET.ParseError) as exc:
        return fail([str(exc)])

    with MATRIX_PATH.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        columns = set(reader.fieldnames or ())
        missing_columns = REQUIRED_COLUMNS - columns
        if missing_columns:
            return fail(
                [
                    "missing required columns: "
                    + ", ".join(sorted(missing_columns))
                ]
            )
        rows = list(reader)

    by_role: dict[str, dict[str, str]] = {}
    for line_number, row in enumerate(rows, start=2):
        role_key = (row.get("role_key") or "").strip()
        group_xmlid = (row.get("stable_odoo_group") or "").strip()
        status = (row.get("status") or "").strip().upper()

        if not role_key:
            errors.append(f"line {line_number}: role_key is empty")
            continue
        if role_key in by_role:
            errors.append(f"line {line_number}: duplicate role_key {role_key!r}")
            continue
        by_role[role_key] = row

        if group_xmlid not in defined_group_xmlids:
            errors.append(
                f"{role_key}: {group_xmlid!r} is not defined as res.groups "
                f"in {GROUPS_PATH.relative_to(ROOT)}"
            )
        if status not in VALID_STATUSES:
            errors.append(
                f"{role_key}: unsupported status {status!r}; expected one of "
                + ", ".join(sorted(VALID_STATUSES))
            )
        elif status == "MISSING":
            errors.append(
                f"{role_key}: status is MISSING even though its implemented "
                "group is required by this matrix"
            )

    actual_role_keys = set(by_role)
    missing_roles = EXPECTED_ROLE_KEYS - actual_role_keys
    unexpected_roles = actual_role_keys - EXPECTED_ROLE_KEYS
    if missing_roles:
        errors.append(
            "missing role rows: " + ", ".join(sorted(missing_roles))
        )
    if unexpected_roles:
        errors.append(
            "unexpected role rows: " + ", ".join(sorted(unexpected_roles))
        )

    for matrix_role, code_role in MATRIX_ROLE_TO_CODE_ROLE.items():
        row = by_role.get(matrix_role)
        if not row:
            continue
        implemented_group = role_group_xmlids.get(code_role)
        if implemented_group is None:
            errors.append(
                f"{matrix_role}: membership role {code_role!r} is missing from "
                "ROLE_GROUP_XMLIDS"
            )
            continue
        documented_group = (row.get("stable_odoo_group") or "").strip()
        if documented_group != implemented_group:
            errors.append(
                f"{matrix_role}: matrix has {documented_group!r}; "
                f"ROLE_GROUP_XMLIDS implements {implemented_group!r}"
            )

    for matrix_role, implemented_group in ADMIN_ROLE_GROUPS.items():
        row = by_role.get(matrix_role)
        if not row:
            continue
        documented_group = (row.get("stable_odoo_group") or "").strip()
        if documented_group != implemented_group:
            errors.append(
                f"{matrix_role}: matrix has {documented_group!r}; "
                f"runtime authority uses {implemented_group!r}"
            )

    if errors:
        return fail(errors)

    print(
        "campaign authority matrix: PASS "
        f"({len(rows)} roles, all groups resolve, no MISSING statuses)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
