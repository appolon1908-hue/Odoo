# Codestra Middleware Bridge

This Odoo 19 add-on is the narrow application boundary between the separate
Codestra Middleware authority and Odoo-owned business records. It does not
implement provider orchestration, expose generic model writes, or connect
directly to PostgreSQL.

The canonical lead command is:

```text
POST /codestra/middleware/v1/commands/crm.lead.upsert
```

The route accepts only the versioned `crm.lead.upsert` command shape, requires a
dedicated single-business-unit service identity, verifies an HMAC signature and
signed identity headers, and enforces tenant-scoped idempotency. The command ID,
idempotency evidence, external mapping, CRM mutation, consent ledger, and hashed
suppression changes commit in one Odoo transaction.

Consent is written to `call.center.consent`. Explicit denial and DNC state are
written to `call.center.suppression` as SHA-256 identifier hashes; plaintext
phone numbers and email addresses are not stored in the suppression table.
Review-pending commands fail closed for contact without fabricating a DNC entry.

Outbound destinations must be credential-free HTTPS URLs. All business writes
remain inside Odoo's ORM and this approved resource-specific service boundary.
