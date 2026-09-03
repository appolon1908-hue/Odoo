# Codestra MoneyBee CRM

`codestra_moneybee_crm` projects privacy-safe MoneyBee account identity into Odoo 19 CRM contacts through the Codestra Middleware command boundary.

## Authority boundary

- Keycloak owns passwords, MFA, login verification, recovery, access tokens, and refresh tokens.
- MoneyBee Backend owns MoneyBee user and organization identifiers.
- Middleware is the only cross-system command writer.
- Odoo owns the CRM/contact projection and immutable command receipt.
- Browsers, n8n, and provider services do not write MoneyBee identity fields directly.

## Canonical command

```text
command_type=crm.contact.upsert.v1
schema_version=1
```

The command requires `command_id`, `source_event_id`, `tenant_id`, and a payload containing a matching `organization_id`, `user_id`, verified email, and a supported `BORROWER` or `LENDER` membership type.

Exact replays return the original applied receipt. Reuse of a command ID with different content, cross-tenant input, unverified email, unsupported membership, or identity-secret material fails closed.

## Security

Only users in `codestra_moneybee_crm.group_moneybee_middleware` may write MoneyBee identity fields or create integration receipts. Passwords, OTPs, verification hashes, reset material, SMTP credentials, Keycloak credentials, and bearer tokens are rejected recursively before persistence.

The model imports only `psycopg2.IntegrityError`, and only to reconcile unique-constraint races inside Odoo-managed savepoints. It never opens an external database connection.

## Testing

The Odoo transaction tests cover:

- dedicated-principal enforcement;
- first application and exact replay;
- changed-content command conflicts;
- nested secret rejection;
- tenant/payload agreement;
- immutable MoneyBee user mapping.

Run through the repository's pinned Odoo 19/PostgreSQL test workflow. Source merge does not install the module, migrate a live database, or enable `ODOO_WRITE`.