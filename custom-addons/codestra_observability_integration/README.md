# Codestra Kyyow observability integration

This addon is the Odoo-side projection boundary for the Kyyow observability
contract. Middleware is the only external writer. The service API accepts
bounded, signed KPI snapshots and incident state transitions, verifies the
dedicated OAuth scope and tenant allowlist, and writes immutable ORM records.

The addon deliberately does not accept raw Prometheus samples, Alertmanager
payloads, logs, traces, message bodies, or secrets. Replays with the same event
and projection hash return the original receipt; changed payloads or stale
incident revisions are rejected.

Required Odoo configuration before activation:

- `codestra.integration.observability_service_user_id` points to the dedicated service user in `group_codestra_observability_service`.
- `codestra.observability.tenant_ids` is a non-empty comma-separated allowlist.
- Keycloak must issue `odoo.observability.kpis.write`, `odoo.observability.incidents.write`, and `odoo.observability.read` through the registered Middleware client.

Projection operation identifiers use the canonical `odoo.observability.*` names.
Only schema fields plus the signed transport bindings `operation`,
`idempotency_key`, and `causation_id` are accepted. Unknown fields are rejected,
including fields that would otherwise be omitted from the projection hash.

Each incident event stores its original response receipt. Replaying an older
event after later transitions returns that event's state, version, correlation
and receipt, with the original HTTP 201 response. Responses do not contain a
mutable duplicate indicator. Concurrent unique conflicts retry the entire Odoo
transaction with a fresh snapshot; updates lock the incident before version
validation. `scripts/test_observability_concurrency.py` tests independent real
transactions after module installation.
