# Disabled staging transport contract

Verified Provider evidence identifies Postal 3.3.7 inbound routes as the
supported mechanism. No support/admin route exists yet, and this staging work
does not create one.

Selected transport: `POSTAL_ROUTE`.

Future approved flow:

1. Postal accepts SMTP outside Kong.
2. Fourteen non-wildcard Postal routes target a Klyrow inbound processor.
3. The processor parses RFC822/MIME, applies size/type limits, and emits the
   normalized schema in `inbound-event.schema.json`.
4. Provider `10.40.0.4` calls middleware `10.40.0.1` over VLAN 4001 using mTLS
   and an HMAC-signed body. Required headers are timestamp, event ID,
   idempotency key, and correlation ID. Secrets are never query parameters.
5. Middleware verifies certificate identity, source, signature, timestamp,
   replay cache, schema, recipient allowlist, and body limits.
6. Middleware invokes the Odoo model service with its authenticated service
   identity. Odoo has no public ingestion controller.

Staging state:

- Postal routes: not created
- Live inbound: disabled
- External outbound: disabled in every queue
- Kong route: none
- Public Odoo endpoint: none
