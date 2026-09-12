# Codestra transactional email through Middleware

This optional bridge replaces Odoo's outbound SMTP call only when
`CODESTRA_EMAIL_ENABLED=true`. It persists one local intent before any network
side effect, submits exactly one transactional recipient to the canonical
Middleware communications API, and thereafter reconciles only by idempotency
key and message-event read-back. Odoo is not allowed to call Klyrow or Postal.

Live submission additionally requires `ALLOW_LIVE_EMAIL=true`. Closing that
switch stops new POSTs while reconciliation GETs continue. Both flags default
to false. Campaign/bulk mail, CC, multiple recipients, and attachments are not
accepted by this bridge.

Required runtime configuration:

- `CODESTRA_EMAIL_API_BASE_URL` — credential-free HTTPS Middleware origin
- `CODESTRA_EMAIL_TOKEN_URL` — Keycloak token endpoint
- `CODESTRA_EMAIL_CLIENT_SECRET_FILE` — mounted `odoo-email` secret file
- `CODESTRA_EMAIL_CA_FILE` — mounted CA bundle
- `CODESTRA_EMAIL_TENANT_ID` — immutable tenant binding
- `CODESTRA_EMAIL_COMPANY_ID` — Odoo company binding
- `CODESTRA_EMAIL_SENDER` — exact approved sender

The durable projection is `codestra.email.outbox`; `mail.mail` remains outgoing
until the Middleware/Klyrow event lifecycle reports delivered. The existing
authenticated `/codestra/middleware/v1/email-events` callback route projects
later events into the same outbox; it is not duplicated by this module. Bounce,
complaint, suppression, rejection, failure, deferral, and provider acceptance
remain distinct operator-visible states.

GET-only reconciliation covers ambiguous submission and callback delay.
Delivered messages leave the polling queue, while a later authenticated
complaint or unsubscribe/suppression callback can still update the durable
projection. Lifecycle precedence is monotonic: a delayed lower-precedence
callback cannot regress a delivered or complained message.
