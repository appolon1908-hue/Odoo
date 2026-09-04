# Agent event delivery

Agent onboarding events use the canonical signed Odoo ingress rather than the
campaign-design preview endpoint.

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

The two public event types are:

```text
codestra.odoo.agent.provisioning_requested
codestra.odoo.agent.activation_email_requested
```

Delivery acknowledgement means only that Middleware durably accepted the event.
The Odoo outbox remains `PROCESSING` at the integration level until the normal
result inbox receives verified provider read-back. No password, bearer token,
HMAC value, generated Keycloak action link, customer data dump, or production
credential is persisted in the outbox.
