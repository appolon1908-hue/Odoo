# ADR-002: Middleware is the only operational VICIdial gateway

- Status: Accepted for staging implementation
- Date: 2026-08-28

## Decision

Odoo, n8n, browser clients, and AI services never write directly to VICIdial
tables. Odoo records business desired state and a transactional outbox event.
Authenticated middleware validates policy, idempotency, business-unit ownership,
campaign scope, and feature flags. Only the restricted VICIdial-side adapter may
perform allowlisted local mutations, followed by read-back and reconciliation.

All new integration and delivery flags default false and fail closed. Remote calls
do not run inside the Odoo business transaction. No secret, database credential,
or general SQL capability is stored in this repository or exposed by an endpoint.

## Consequences

Existing direct-network or database paths must be inventoried and removed or
isolated before production. A configuration record or mocked response is not a
`PASS`; functional staging execution, read-back, and retained evidence are needed.
