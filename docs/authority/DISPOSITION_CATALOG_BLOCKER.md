# Missing controlled disposition catalog

Status: `MISSING`

The authority states that `odoo_campaign_disposition_catalog.csv` contains 2,677
campaign-owned rows across all 93 mapped channels. That file was not included in
the attachment, is not present in the Odoo repository, and was not found in the
local attachment set inspected on 2026-08-28.

This is a hard input blocker for `feat/cc-scripts-dispositions` and for any
provisioning, reconciliation, or production gate that depends on the catalog.
Examples in the prose are insufficient because the controlled rows must include
the native status code, full name, Odoo stage, required fields, callback behavior,
suppression behavior, reporting category, and event name.

Required resolution:

1. Supply the original controlled CSV.
2. Verify that it has exactly 2,677 data rows and covers all 93 canonical campaign
   channels.
3. Validate native status length, uniqueness within the applicable VICIdial scope,
   referential integrity, and campaign ownership.
4. Record a source hash and review approval.
5. Import only into a disposable staging database with all live flags false.

No placeholder CSV is committed because an empty or invented file could be
mistaken for authoritative seed data.
