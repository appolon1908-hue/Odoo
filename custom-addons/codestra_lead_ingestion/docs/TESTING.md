# Testing

Run against a disposable production-derived database:

```bash
odoo -d DATABASE --addons-path=ODOO_ADDONS,CUSTOM_ADDONS \
  -u codestra_lead_ingestion --stop-after-init --without-demo=true \
  --test-enable --test-tags=/codestra_lead_ingestion
```

The suite covers defaults, uploader identity, CSV parsing, checksum
idempotency, illegal transitions, approval authorization and attribution,
phone quarantine/error reports, CRM/outbox transaction creation,
reconciliation completion blocking, and append-only audit.

Provider, VICIdial, middleware, n8n and production activation gates require
separate contract/E2E evidence and must not be inferred from module tests.
