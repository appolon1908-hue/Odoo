# Codestra MoneyBee CRM

`codestra_moneybee_crm` projects privacy-safe MoneyBee account identity into Odoo 19 CRM contacts through one tenant-bound Codestra Middleware command.

## Authority boundary

- Keycloak owns passwords, MFA, login verification, recovery, access tokens, and refresh tokens.
- MoneyBee Backend owns MoneyBee user and organization identifiers.
- Middleware is the only cross-system command writer.
- Odoo owns the company-scoped CRM/contact projection and immutable command receipt.
- Browsers, n8n, and provider services do not write MoneyBee identity fields or receipts directly.

## Principal and tenant binding

Each MoneyBee Middleware service user must:

1. belong to `codestra_moneybee_crm.group_moneybee_middleware`;
2. have exactly one allowed Odoo company;
3. run with that same company active; and
4. use an Odoo company whose server-managed `moneybee_organization_id` is populated.

The authenticated user's single allowed company and that company's configured identifier are authoritative. `command.tenant_id` and `payload.organization_id` must both match; caller-supplied tenant strings never establish scope.

## Canonical command

```text
command_type=crm.contact.upsert.v1
schema_version=1
```

The only public mutation entry point is
`res.partner.moneybee_apply_contact_command(command)`. The lower-level upsert
method is private. Contact create/write operations from the MoneyBee service
principal are rejected unless they carry an in-process capability token that
cannot be supplied through JSON-RPC.

The command requires `command_id`, `source_event_id`, `tenant_id`, and a payload
containing a matching `organization_id`, `user_id`, verified email, and a
supported `BORROWER` or `LENDER` membership type.

Exact replays return the original applied receipt. Reuse of a command ID with
different content, cross-tenant input, an unbound or multi-company principal,
unverified email, unsupported membership, or identity-secret material fails
closed.

## Receipt integrity

Receipts are created only by the internal command path and are immutable after
creation. The Middleware identity has read/create ACLs solely so the internal
ORM transaction can persist a receipt; a server-side opaque capability check
rejects direct RPC create/copy calls. Write and delete are always rejected.

A record rule limits a Middleware identity to receipts created by that exact
user inside its one allowed company. Administrators may read receipts but do
not receive an ORM mutation path.

## Security

MoneyBee-managed identity, organization, company, and verified-email fields
cannot be changed outside the receipted command path. MoneyBee-mapped contacts
cannot be deleted through the ORM. Human CRM users may continue to maintain
Odoo-owned business fields such as display name, phone, assignments, and notes.

Passwords, OTPs, verification hashes, reset material, SMTP credentials,
Keycloak credentials, and bearer tokens are rejected recursively before
persistence.

The model imports only `psycopg2.IntegrityError`, and only to reconcile
unique-constraint races inside Odoo-managed savepoints. It never opens an
external database connection.

## Testing

The Odoo transaction tests cover principal enforcement, exact replay,
changed-content conflicts, recursive secret rejection, single-company binding,
command/payload/principal tenant agreement, cross-tenant identity rejection,
receipt isolation and immutability, direct contact-write denial, and
display-name preservation.

Run through the repository's pinned Odoo 19/PostgreSQL test workflow. Source
merge does not install the module, migrate a live database, enable `ODOO_WRITE`,
or authorize runtime deployment.
