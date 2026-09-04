# MoneyBee CRM account synchronization

`codestra_moneybee_crm` is the Odoo-side consumer for the Middleware command
`crm.contact.upsert.v1`.

## Authority boundaries

- Keycloak owns passwords, MFA, login email verification, and recovery.
- MoneyBee Backend owns MoneyBee user and organization identifiers.
- Middleware is the only cross-system command boundary.
- Odoo owns the company-scoped CRM/contact projection and immutable command receipt.

## Authenticated tenant scope

Provision a dedicated non-interactive Odoo user in
`codestra_moneybee_crm.group_moneybee_middleware`. The user must have exactly one
allowed company, that company must be active for the request, and the company
must carry the authoritative `moneybee_organization_id`.

The command's `tenant_id` and the payload's `organization_id` are assertions
that must match the server-side company mapping. They are not accepted as the
source of tenant authority. An unbound principal, a principal with multiple
allowed companies, an active-company mismatch, or cross-tenant input fails
closed before contact lookup or mutation.

## Mutation and receipt boundary

`moneybee_apply_contact_command` is the only public MoneyBee contact mutation
method. Its lower-level upsert is private. The service identity cannot create or
write contacts directly because model-layer guards require an opaque in-process
capability token. MoneyBee-managed user, organization, company, and verified
email fields are protected from unreceipted edits.

The receipt model applies the same pattern: direct create/copy calls are denied,
write and delete are always denied, and a principal/company record rule hides
all other service identities' receipts. Exact command replay returns the
original receipt. Reusing a command ID with different content fails closed.

## Payload limits

The command may carry `user_id`, `organization_id`, verified email, display
name, membership type, and reviewed business attributes. Passwords, OTPs,
verification hashes, reset links, access/refresh tokens, SMTP credentials, and
Keycloak credentials are rejected recursively.

The Odoo mapping remains idempotent by globally unique `moneybee_user_id`. If an
identity is already mapped to a different tenant/company, synchronization fails
closed and requires reconciliation rather than guessing which record is
authoritative.

Source merge alone does not install or upgrade the addon, mutate a live Odoo
database, enable `ODOO_WRITE`, or authorize staging/production deployment.
