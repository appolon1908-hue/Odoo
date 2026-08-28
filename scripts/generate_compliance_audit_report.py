#!/usr/bin/env python3
"""Generate the fail-closed campaign compliance and audit readiness matrix."""

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reports" / "odoo-vicidial-campaign-matrix.csv"
TARGET = ROOT / "reports" / "odoo-compliance-audit-matrix.csv"


def main():
    with SOURCE.open(newline="", encoding="utf-8") as stream:
        campaigns = list(csv.DictReader(stream))
    if len(campaigns) != 93:
        raise SystemExit(f"expected 93 controlled campaigns, found {len(campaigns)}")

    rows = []
    seen = set()
    for campaign in campaigns:
        code = campaign["canonical_campaign_code"]
        if code in seen:
            raise SystemExit(f"duplicate campaign code: {code}")
        seen.add(code)
        rows.append(
            {
                "canonical_campaign_code": code,
                "business_unit_code": campaign["business_unit_code"],
                "direction": campaign["direction"],
                "compliance_policy_status": "MISSING",
                "consent_evidence_status": "STAGING_READY",
                "suppression_status": "STAGING_READY",
                "calling_hours_status": "STAGING_READY",
                "payment_safety_status": "STAGING_READY",
                "retention_hold_status": "STAGING_READY",
                "append_only_audit_status": "STAGING_READY",
                "break_glass_status": "STAGING_READY",
                "live_outreach_flags": "FALSE",
                "external_state_readback": "NOT_TESTED",
                "status": "PARTIAL",
            }
        )

    with TARGET.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    print("COMPLIANCE_AUDIT_MATRIX_ROWS=93")
    print("COMPLIANCE_POLICIES_PRESENT=0")
    print("LIVE_OUTREACH_FLAGS_ENABLED=0")
    print("EXTERNAL_COMPLIANCE_READBACK=NOT_TESTED")
    print("COMPLIANCE_AUDIT_STATUS=PARTIAL")


if __name__ == "__main__":
    main()
