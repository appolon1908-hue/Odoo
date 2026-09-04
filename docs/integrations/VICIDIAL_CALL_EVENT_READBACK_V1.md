# VICIdial call-event readback v1

## Purpose

Middleware uses this read-only endpoint only after a call-event POST has an
uncertain transport outcome.  It proves whether Odoo already recorded the event
before Middleware permits a retry.  It does not place, answer, transfer, or end
a call.

```text
GET /codestra/api/v1/call-events/{event_id}
```

## Authentication

The endpoint requires all of the following headers:

```text
X-Codestra-Signature-Version: v2
X-Codestra-Timestamp: <epoch seconds>
X-Codestra-Event-ID: <same event_id as the path>
X-Codestra-Tenant-ID: <authoritative tenant>
X-Codestra-Signature: sha256=<lowercase hex>
```

The signature input is the UTF-8 encoding of:

```text
v2
GET
/codestra/api/v1/call-events/{event_id}
{timestamp}
{event_id}
{tenant_id}
{sha256(empty request body)}
```

The timestamp acceptance window is at most 300 seconds.  The route, event ID,
tenant, and empty body are all bound into the signature.  The configured secret
must contain at least 32 bytes.

## Successful response

The response contains only bounded reconciliation evidence:

```json
{
  "schema_version": "1.0",
  "event_id": "evt-123",
  "tenant_id": "COD",
  "call_id": "call-123",
  "event_type": "call.connected",
  "sequence": 3,
  "processing_state": "processed",
  "payload_hash": "<sha256>",
  "correlation_id": "corr-123",
  "occurred_at": "2026-09-04 16:00:00",
  "call_state": "connected"
}
```

No phone number, customer details, notes, recording URL, raw event payload, or
credential material is returned.  A missing event returns `404`; a tenant
mismatch returns `403`.  Responses use `Cache-Control: no-store`.

## Safety state

This source change does not enable `ODOO_WRITE`, VICIdial writes, callbacks,
transfers, dialing, or production deployment.  Staging must first prove an
accepted POST, an intentionally interrupted response, successful readback, and
zero duplicate call-event rows.
