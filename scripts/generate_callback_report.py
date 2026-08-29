#!/usr/bin/env python3
"""Generate the campaign callback readiness matrix from the controlled IDs."""

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reports" / "odoo-vicidial-campaign-matrix.csv"
TARGET = ROOT / "reports" / "odoo-callback-matrix.csv"

FIELDNAMES = [
    "canonical_campaign_code",
    "business_unit_code",
    "direction",
    "technical_callback_compatibility",
    "agent_login_allowed",
    "callback_policy_status",
    "callback_record_status",
    "appointment_status",
    "reminder_status",
    "same_campaign_recovery",
    "callback_publication_enabled",
    "external_readback_status",
    "status",
]


def main():
    with SOURCE.open(newline="", encoding="utf-8") as source_file:
        source_rows = list(csv.DictReader(source_file))
    if len(source_rows) != 93:
        raise SystemExit(f"expected 93 controlled campaign rows, found {len(source_rows)}")

    output_rows = []
    seen = set()
    for row in source_rows:
        campaign_code = row["canonical_campaign_code"]
        if campaign_code in seen:
            raise SystemExit(f"duplicate campaign code: {campaign_code}")
        seen.add(campaign_code)
        technical = row["technical_callback_compatibility"] == "TRUE"
        output_rows.append(
            {
                "canonical_campaign_code": campaign_code,
                "business_unit_code": row["business_unit_code"],
                "direction": row["direction"],
                "technical_callback_compatibility": "TRUE" if technical else "FALSE",
                "agent_login_allowed": row["agent_login_allowed"],
                "callback_policy_status": "MISSING",
                "callback_record_status": "NOT_TESTED",
                "appointment_status": "NOT_TESTED",
                "reminder_status": "NOT_TESTED",
                "same_campaign_recovery": "STAGING_READY",
                "callback_publication_enabled": "FALSE",
                "external_readback_status": "NOT_TESTED",
                "status": "PARTIAL",
            }
        )

    with TARGET.open("w", newline="", encoding="utf-8") as target_file:
        writer = csv.DictWriter(target_file, fieldnames=FIELDNAMES, lineterminator="\n")
        writer.writeheader()
        writer.writerows(output_rows)
    print(f"CALLBACK_MATRIX_ROWS={len(output_rows)}")
    print("CALLBACK_PUBLICATION_ENABLED=0")
    print("CALLBACK_MATRIX_STATUS=PARTIAL")


if __name__ == "__main__":
    main()
