# Codestra Odoo identity and webhook contract

This repository currently contains a secure Odoo 19 GitOps scaffold, not the
reviewed integration addon implementation.

## Machine identity

```text
issuer=https://auth.codestra.co/realms/codestra
client_id=odoo-integration
grant_type=client_credentials
maximum_access_token_lifetime_seconds=300
```

Middleware calls the Odoo adapter with audience `odoo-integration` and only:

```text
odoo.activities.write
odoo.leads.read
odoo.leads.write
```

Odoo publishes back to `middleware-api` with only:

```text
odoo.delivery.result.publish
odoo.events.publish
```

n8n has no direct Odoo grant.

## Signed event callback

```text
POST ${MIDDLEWARE_API_BASE_URL}/api/v1/odoo/events
```

The callback requires short-lived OIDC bearer authentication, HMAC-SHA256,
tenant/event/source/timestamp/signature/correlation headers, stable event IDs,
24-hour replay retention, and idempotent at-least-once processing.

Canonical event types:

```text
codestra.odoo.activity.completed
codestra.odoo.lead.created
codestra.odoo.lead.updated
```

## Implementation gate

A later reviewed PR must add the Odoo 19 addon under `custom-addons/`, including
models for durable inbox/outbox state, tenant and company mapping, least-
privilege system parameters, duplicate/replay tests, migration and rollback
tests, and staging evidence with external delivery disabled.
