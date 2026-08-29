# Call Center Campaign

This Odoo 19 add-on owns campaign, team, script, lifecycle, transactional-outbox and integration-result models used by the Codestra call-center platform.

## Boundaries

- Odoo remains the business system of record.
- Cross-system delivery is performed through the Codestra middleware contract.
- The add-on never opens a separate PostgreSQL connection or exposes database credentials.
- Local cursor SQL is limited to reviewed row-locking, readiness and read-only projection operations declared against the exact module tree.

## Safety

Campaign fixtures and automation definitions install inactive. External delivery, callbacks, email, SMS and dialing remain fail-closed until their independent production gates are approved.

## Verification

Run the module tests together with `scripts/run_ci.sh`; the canonical baseline and integration-boundary validators reject undeclared tree drift or SQL/import exceptions.
