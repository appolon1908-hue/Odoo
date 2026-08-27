# MoneyBee CRM account synchronization

`codestra_moneybee_crm` is the Odoo-side consumer for the Middleware command
`crm.contact.upsert.v1`.

Authority boundaries:

- Keycloak owns passwords, MFA, login email verification and recovery.
- MoneyBee Backend owns the MoneyBee user and organization identifiers.
- Middleware is the only cross-system command boundary.
- Odoo owns the CRM/contact business view only.

The command may carry `user_id`, `organization_id`, verified email, display
name, membership type and reviewed business attributes. Passwords, OTPs,
verification hashes, reset links, access/refresh tokens and SMTP/Keycloak
credentials are rejected.

The Odoo mapping is idempotent by `moneybee_user_id`. If historical data contains
multiple partners with the same mapping, synchronization fails closed and
requires reconciliation rather than guessing which record is authoritative.
