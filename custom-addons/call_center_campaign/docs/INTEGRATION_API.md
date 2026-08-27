# Odoo Integration API

This module exposes the Odoo-owned companion routes for the Codestra
middleware integration client:

- `POST /api/v1/integration/outbox/claims`
- `GET /api/v1/integration/outbox/{outbox_id}`
- `POST /api/v1/integration/outbox/{outbox_id}/lease/renew`
- `POST /api/v1/integration/outbox/{outbox_id}/acknowledgements`
- `POST /api/v1/integration/outbox/{outbox_id}/failures`
- `POST /api/v1/integration/outbox/{outbox_id}/release`
- `POST /api/v1/integration/results`
- `GET /api/v1/integration/results/{result_public_id}`
- `GET /api/v1/integration/results?delivery_id={delivery_id}`
- `POST /api/v1/integration/results/{result_public_id}/reconcile`
- `GET /api/v1/integration/desired-state/{aggregate_type}/{public_id}`
- `GET /api/v1/integration/agents/{agent_public_id}`
- `GET /api/v1/integration/leads/{lead_public_id}`
- `GET /api/v1/integration/campaigns/{campaign_public_id}`
- `GET /api/v1/integration/traces/{correlation_id}`
- `GET /api/v1/integration/traces?model={model}&res_id={id}`
- `GET /api/v1/integration/audit/{audit_id}`
- `GET /api/v1/integration/capabilities`

The standard operations routes are:

- `GET /health/live` — minimal liveness; private-network exposure only
- `GET /health/ready` — requires `monitor.read`
- `GET /.well-known/codestra-service` — requires `service.attest`
- `GET /metrics` — requires `metrics.read`

All routes use Odoo ORM-backed authoritative models. Outbox claims use
`FOR UPDATE SKIP LOCKED`, opaque lease tokens, and monotonically increasing
lease generations. Raw lease tokens are returned only to the claiming worker;
only their SHA-256 hashes are stored.

Requests require a short-lived signed service JWT, exact audience, an
allowlisted service identity, route-specific scope, timestamp, nonce, and body
hash. Writes additionally require immutable idempotency, request, correlation,
and causation headers. Environment, business-unit, and campaign scope are
checked against both the token and the authoritative Odoo record.

No route writes directly to PostgreSQL except the bounded locking query used to
claim existing ORM records. No route contacts VICIdial, Asterisk, n8n, or an
external provider. Production activation is not part of this module.

## Webhook boundary

Odoo does not expose a provider webhook. Public provider callbacks terminate at
middleware, where raw-body authentication, replay protection, normalization,
and quarantine occur. Middleware sends only a normalized, authenticated result
to `odoo.results.create`.

The retired `/codestra/integration/v1/results` path always returns HTTP 410.
There is no static URL fallback.
