#!/usr/bin/env python3
"""Generate fail-closed script/disposition matrices from the controlled IDs."""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reports" / "odoo-vicidial-campaign-matrix.csv"


def write_report(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    with SOURCE.open(encoding="utf-8", newline="") as stream:
        campaigns = list(csv.DictReader(stream))
    if len(campaigns) != 93:
        raise SystemExit(f"expected 93 controlled campaigns, found {len(campaigns)}")

    scripts = []
    dispositions = []
    for campaign in campaigns:
        common = {
            "canonical_campaign_code": campaign["canonical_campaign_code"],
            "vicidial_campaign_id": campaign["vicidial_campaign_id"],
            "business_unit_code": campaign["business_unit_code"],
            "direction": campaign["direction"],
        }
        scripts.append(
            {
                **common,
                "catalog_vicidial_script_id": "MISSING",
                "canonical_owner": "cc.script/cc.script.version",
                "external_publication_enabled": "FALSE",
                "external_readback_status": "NOT_TESTED",
                "status": "PARTIAL",
            }
        )
        dispositions.append(
            {
                **common,
                "controlled_catalog_rows": "0",
                "canonical_owner": "cc.disposition.set/cc.disposition",
                "catalog_status": "MISSING",
                "approval_state": "BLOCKED",
                "external_readback_status": "NOT_TESTED",
                "status": "BLOCKED",
            }
        )

    write_report(
        ROOT / "reports" / "odoo-vicidial-script-matrix.csv",
        list(scripts[0]),
        scripts,
    )
    write_report(
        ROOT / "reports" / "odoo-vicidial-disposition-matrix.csv",
        list(dispositions[0]),
        dispositions,
    )
    print("SCRIPT_MATRIX_ROWS=93")
    print("DISPOSITION_MATRIX_ROWS=93")
    print("CONTROLLED_DISPOSITION_ROWS=0")
    print("DISPOSITION_CATALOG_GATE=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
