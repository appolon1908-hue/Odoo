#!/usr/bin/env python3
"""Generate fail-closed recording and quality readiness matrices."""

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reports" / "odoo-vicidial-campaign-matrix.csv"


def write_report(path, rows):
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main():
    with SOURCE.open(newline="", encoding="utf-8") as stream:
        campaigns = list(csv.DictReader(stream))
    if len(campaigns) != 93:
        raise SystemExit(f"expected 93 controlled campaigns, found {len(campaigns)}")

    recordings = []
    quality = []
    seen = set()
    for campaign in campaigns:
        code = campaign["canonical_campaign_code"]
        if code in seen:
            raise SystemExit(f"duplicate campaign code: {code}")
        seen.add(code)
        common = {
            "canonical_campaign_code": code,
            "business_unit_code": campaign["business_unit_code"],
            "direction": campaign["direction"],
        }
        recordings.append(
            {
                **common,
                "recording_policy_status": "MISSING",
                "canonical_binding_status": "NOT_TESTED",
                "metadata_contract_status": "STAGING_READY",
                "redaction_status": "NOT_TESTED",
                "retention_status": "NOT_TESTED",
                "legal_hold_status": "NOT_TESTED",
                "recording_playback_enabled": "FALSE",
                "external_storage_readback": "NOT_TESTED",
                "status": "PARTIAL",
            }
        )
        quality.append(
            {
                **common,
                "quality_program_status": "MISSING",
                "scorecard_status": "MISSING",
                "sampling_status": "NOT_TESTED",
                "evaluation_status": "STAGING_READY",
                "separate_finalizer_status": "STAGING_READY",
                "calibration_status": "STAGING_READY",
                "dispute_status": "STAGING_READY",
                "coaching_status": "STAGING_READY",
                "ai_assist_enabled": "FALSE",
                "status": "PARTIAL",
            }
        )

    write_report(ROOT / "reports" / "odoo-recording-policy-matrix.csv", recordings)
    write_report(ROOT / "reports" / "odoo-quality-program-matrix.csv", quality)
    print("RECORDING_POLICY_MATRIX_ROWS=93")
    print("QUALITY_PROGRAM_MATRIX_ROWS=93")
    print("RECORDING_PLAYBACK_ENABLED=0")
    print("AI_ASSIST_ENABLED=0")
    print("RECORDING_QUALITY_STATUS=PARTIAL")


if __name__ == "__main__":
    main()
