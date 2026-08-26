## Summary

Describe the Odoo module or deployment-control change and the business behavior affected.

## Modules affected

- Module name(s):
- Install, upgrade, or configuration-only:
- Database schema or data migration involved: yes / no

## Validation

- [ ] No secrets, database dumps, filestore data, certificates, or runtime files are included.
- [ ] Python syntax and manifest validation pass.
- [ ] Module clean-install test passes on an empty test database.
- [ ] Module upgrade test passes on a representative staging database.
- [ ] Access rights and record rules were tested for affected roles.
- [ ] Existing data and attachments were reconciled after upgrade.
- [ ] External delivery, dialing, and live integration capabilities stayed disabled during validation.
- [ ] A matching PostgreSQL and filestore recovery point exists when data changes are involved.
- [ ] Rollback steps are documented and rehearsed where required.
- [ ] The exact reviewed commit SHA will be deployed; no server-side edits will be made.

## Evidence

Link test logs, screenshots, migration results, and the staging health check.

## Deployment notes

List the exact comma-separated module names to pass to Odoo's `-u` option and any required order of operations.
