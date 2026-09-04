# Codestra VICIdial Call Event Readback

This additive Odoo 19 module provides the read-only evidence endpoint used by Middleware after an ambiguous call-event POST outcome.

```text
GET /codestra/api/v1/call-events/{event_id}
```

It depends on `codestra_vicidial_crm` but does not modify that reviewed call-processing subtree. The endpoint requires the existing HMAC timestamp/event headers plus `X-Codestra-Tenant-ID`, verifies the event's bound call tenant, and returns only bounded lifecycle identity. It never creates or changes an Odoo record.

A `404` is the only response that proves the event is absent and permits Middleware to retry the same event ID. A timeout, `5xx`, malformed response, or identity mismatch remains an unknown outcome and must not be blindly retried.

Merging the module does not install it on a server, enable Odoo writes, or authorize call control or production dialing.
