# VICIdial real-time call projection

The new internal endpoint accepts only tenant-bound, signed Middleware call
lifecycle projections. It validates the existing campaign, active agent,
extension, tenant, and Keycloak subject before creating or advancing a call.
Every accepted event is idempotent and sequence-aware, and uncertain Middleware
outcomes can be resolved through the signed status endpoint.

Odoo remains the CRM and agent-workspace authority. It does not carry RTP/SRTP
audio. The existing `codestra.call` Odoo Bus notification remains the real-time
browser channel, but `_notify_agent` now fails closed unless both call-event
projection and the separate `ENABLE_WEBSOCKET_SCREEN_POP` feature flag are
enabled.

Committed defaults keep projection disabled and synthetic-only. Non-synthetic
traffic requires a separate activation reference. The service credential and
HMAC secret are configuration values outside Git.
