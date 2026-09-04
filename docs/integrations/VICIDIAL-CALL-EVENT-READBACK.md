# VICIdial call-event read-back contract

## Purpose

`codestra_vicidial_crm` accepts authoritative call lifecycle events only from the governed Middleware path and pushes an agent-scoped `codestra.call` notification through Odoo Bus after the event is applied.

This document adds the read-only evidence endpoint required when Middleware cannot determine whether a POST reached Odoo.

## Endpoints

```text
POST /codestra/api/v1/call-events
GET  /codestra/api/v1/call-events/{event_id}
```

Both endpoints require:

```text
X-Codestra-Timestamp
X-Codestra-Signature
X-Codestra-Event-ID
```

The GET endpoint also requires:

```text
X-Codestra-Tenant-ID
```

The signature remains the established call-event HMAC-SHA256 value over:

```text
<timestamp>.<raw request body>
```

The GET request has an empty body. The timestamp must be within the existing 300-second acceptance window, the header event ID must equal the path event ID, and the requested event must belong to the supplied tenant.

## Read-back result

A matching event returns only bounded lifecycle evidence:

```json
{
  "event_id": "...",
  "event_type": "call.connected",
  "call_id": "...",
  "sequence": 4,
  "state": "connected",
  "payload_hash": "..."
}
```

The response is marked `Cache-Control: no-store`.

## Outcome rules

```text
200 = the exact event is durably present in Odoo
403 = signature, event identity, or tenant identity rejected
404 = event not present; Middleware may classify the previous POST as proven non-delivery
other/timeout = outcome remains unknown and must not be blindly retried
```

A read-back request cannot create or modify an Odoo record. It does not place, answer, hold, transfer, hang up, or redial a call.

## Authority and isolation

- VICIdial/Asterisk remains authoritative for call execution and provider-facing state.
- Middleware remains authoritative for durable ingress, idempotency, delivery, and reconciliation.
- Odoo remains authoritative for the CRM projection, call workspace, notes, disposition, callback, and agent screen.
- The Odoo endpoint validates the configured tenant, campaign, active agent, extension, and Keycloak subject before a new call is established.
- Existing call binding is immutable across tenant, campaign, agent, extension, and Keycloak subject.
- Odoo Bus publishes only to the assigned Odoo user's partner channel.

## Release boundary

Merging this source does not enable Odoo writes. Runtime activation requires a separate protected staging release, exact source and image read-back, the shared secret supplied outside Git, synthetic call lifecycle validation, restart/no-gap evidence, backup/restore, rollback, and continued disabled production dialing.
