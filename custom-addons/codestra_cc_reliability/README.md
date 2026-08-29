# Codestra Contact Center Reliability

Provides the mission-level dependency boundary for transactional outbox, durable inbox, idempotency, leases, dead-letter review, replay authorization, correlation, and reconciliation.

The implementation is supplied by the audited `codestra_integration_hub`, `codestra_middleware_bridge`, and `call_center_orchestration` modules. Cross-system mutations remain Middleware-only; this facade adds no direct provider or database writer.
