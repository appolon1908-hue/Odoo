#!/usr/bin/env python3
"""Generate the fail-closed campaign workforce readiness matrix."""

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reports" / "odoo-vicidial-campaign-matrix.csv"
TARGET = ROOT / "reports" / "odoo-wfm-policy-matrix.csv"


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
                "workforce_policy_status": "MISSING",
                "forecast_status": "NOT_TESTED",
                "schedule_status": "STAGING_READY",
                "adherence_status": "STAGING_READY",
                "exception_queue_status": "STAGING_READY",
                "realtime_snapshot_status": "STAGING_READY",
                "kpi_reporting_policy_status": "MISSING",
                "external_state_readback": "NOT_TESTED",
                "status": "PARTIAL",
            }
        )
    with TARGET.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=list(rows[0]), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    print("WFM_POLICY_MATRIX_ROWS=93")
    print("WFM_POLICIES_PRESENT=0")
    print("REPORTING_POLICIES_PRESENT=0")
    print("WFM_REPORTING_STATUS=PARTIAL")


if __name__ == "__main__":
    main()
