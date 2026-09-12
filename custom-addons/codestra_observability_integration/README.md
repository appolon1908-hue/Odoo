# Codestra Kyyow observability integration

This addon is the Odoo-side projection boundary for the Kyyow observability
contract. Middleware is the only external writer. The service API accepts
bounded, signed KPI snapshots and incident state transitions, verifies the
dedicated OAuth scope and tenant allowlist, and writes immutable ORM records.

The addon deliberately does not accept raw Prometheus samples, Alertmanager
payloads, logs, traces, message bodies, or secrets. Replays with the same event
and projection hash return the original receipt; changed payloads or stale
incident revisions are rejected.
