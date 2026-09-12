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
