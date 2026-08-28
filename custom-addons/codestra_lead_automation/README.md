# Codestra Lead Automation

Separate default-off Odoo module for HMAC-authenticated Middleware application
of policy-authorized lead changes. It contains no recording, telephony,
communication, calendar, or appointment automation.

The contract retains the Middleware PR #65 lineage and coordinates the signed
company-scope 1.1 extension through Middleware PR #68 and this Odoo change. The
Odoo endpoint accepts only the byte-identical `lead-odoo-apply-v1.json` request
and returns the strict `lead-odoo-ack-v1.json` acknowledgement. All fourteen
lead schemas and their SHA-256 manifest remain pinned.

HMAC-V2 signing covers version, exact uppercase method, canonical request path,
timestamp, nonce, service identity, audience, environment, exact
`lead-automation.odoo-apply.write` scope, idempotency key, and transmitted-body
SHA-256. HMAC-V1 and cross-capability scopes are rejected. The endpoint uses the
exact raw HTTP body, rejects replay and query strings, and has no bearer fallback.
Every mutation switch defaults off. n8n cannot call Odoo or PostgreSQL directly.

## Executable multi-company isolation test

Run only against disposable PostgreSQL with the digest-pinned Odoo 19 image:

```sh
odoo --database=lead_automation_mc_ci \
  --init=codestra_lead_automation --without-demo=True --test-enable \
  --test-tags=/codestra_lead_automation:LeadAutomationMultiCompanyIsolationTest \
  --stop-after-init
```

The test creates only `synthetic-logistics-a` and `synthetic-logistics-b`. It
proves same-company access and denies cross-company lead, campaign,
business-unit, and numeric-record substitution without CRM mutation. Delete the
disposable database, container, and internal network afterward. Production
databases and data are prohibited.
