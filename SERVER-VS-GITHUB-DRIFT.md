# Server vs GitHub drift — 2026-08-28

This is a sanitized, read-only baseline. No production service, database, filestore, flag, or integration was changed.

## Result

- Candidate: `4681d755039ee7f4fec21228bac234a668541de8` reconstructed on `reconcile/odoo-canonical-source-v1`.
- Candidate modules: 67. Active `/mnt/extra-addons` modules: 25. Registry custom rows: 32.
- Classifications: {'CONTENT_DRIFT': 20, 'GITHUB_ONLY': 40, 'SENSITIVE_EXCLUDED': 2, 'VERSION_DRIFT': 5}.
- Production source is a mutable host checkout mounted read-only into Odoo and does not match the candidate. It must not be promoted as canonical.
- Two installed registry modules were on a separate/shared addon path and their content was deliberately not copied; they are `SENSITIVE_EXCLUDED`, not unknown.

## Runtime baseline

- Odoo: `19.0-20260630`; image `odoo@sha256:f54272f31d5f77e4146b887efb3761c98480317daf687e4b4b5e76ed8bcc08c5`.
- PostgreSQL: 17.6; database size 92,425,363 bytes.
- Filestore: `/var/lib/odoo/.local/share/Odoo/filestore/codestra_odoo`, 93,816,150 bytes, 224 files; 630 attachment rows.
- Proxy mode enabled; worker/cron process settings were not explicit in the captured config. Registry had 39 cron records.
- Compose project `codestra`; Odoo has no published host port and is attached to backend/edge/integration networks.
- Routing/auth components observed: Caddy, Kong 3.14, Keycloak. Only metadata was captured.

## Effects and flags

All captured production-effect flags were false except `CODESTRA_CALLBACK_SYNC_ENABLED=true`; `CODESTRA_PRODUCTION_CALLBACKS=false` and the database callback/production flags were false. Email, SMS, PSTN, campaign activation, n8n production, transfer, provider-write, and VICIdial-write flags were false. No flag was changed.

## Backups and recovery

The latest observed paired backup was `klyrow-unified-20260822T200000Z` (database plus filestore with checksums), not a current release pair. Existing evidence records a 30-second mechanics exercise but says representative Odoo 19 rollback remains blocked. Recovery is therefore **not certified**.

## Source-candidate validation

- The exact PR head passed a fresh isolated Odoo 19/PostgreSQL 17.6 install: 458 tests, zero failures, zero errors, and zero browser skips.
- The Chrome browser test passed the calendar, reminder, and scheduler pop-outs.
- All 67 custom modules upgraded successfully; the PostgreSQL schema, administrator state, and module state audits passed.
- A disposable database backup/restore rehearsal passed. This validates the source candidate and CI mechanics, not the captured production data or filestore.

## Remaining certification blockers

- Installed-vs-manifest version drift exists on live modules; content drift requires staged migrations, not direct copying.
- Sanitized deployed-baseline upgrade, external integration contracts, authorization-negative scenarios, interruption restart, representative load/soak, and paired database-plus-filestore restore remain required in isolated staging.
- HTTP health and disposable CI success are not accepted as staging or business certification.
