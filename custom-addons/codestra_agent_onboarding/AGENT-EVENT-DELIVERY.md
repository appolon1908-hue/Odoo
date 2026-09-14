# Agent event delivery

Secure activation-email events still use the canonical signed Odoo ingress.
Initial agent provisioning calls Middleware's canonical
`/platform/v1/agent-provisioning/requests` API directly. The old
`agent.provisioning.requested.v1` event is retired and is never delivered.

Required protected runtime bindings:

```text
CODESTRA_MIDDLEWARE_ODOO_EVENTS_URL=https://<private-middleware>/api/v1/odoo/events
CODESTRA_MIDDLEWARE_ODOO_EVENTS_TOKEN_FILE=/run/secrets/odoo-events-token
CODESTRA_MIDDLEWARE_ODOO_EVENTS_HMAC_FILE=/run/secrets/odoo-events-hmac
```

The endpoint must be credential-free HTTPS at the exact path
`/api/v1/odoo/events`. Secret files must be regular, non-symlink files and must
not grant group or other permissions.

The sender wraps each immutable Odoo outbox record in the canonical event
envelope, signs the exact raw JSON body with the Middleware v1 HMAC contract,
and requires an acknowledgement bound to the original event, tenant, and
correlation identity. Accepted and duplicate acknowledgements are safe.

The remaining public event type is:

```text
codestra.odoo.agent.activation_email_requested
```

## Middleware handoff

Odoo is the producer of the remaining activation-email event. Middleware owns
the `POST /api/v1/odoo/events` receiver: it authenticates the bearer token and
HMAC envelope, validates the agent-specific payload, and atomically records the
event in its durable inbox, immutable ledger, and publication outbox. Initial
agent provisioning uses the direct, idempotent saga command instead.

This handoff is intentionally not a direct Odoo-to-Klyrow call. Middleware
downstream processing must complete the governed provisioning and provider
read-back steps before it emits any email command. Receipt at Middleware does
not activate an identity, send mail, or enable production dialing.

Delivery acknowledgement means only that Middleware durably accepted the event.
The Odoo outbox remains `PROCESSING` at the integration level until the normal
result inbox receives verified provider read-back. No password, bearer token,
HMAC value, generated Keycloak action link, customer data dump, or production
credential is persisted in the outbox.
