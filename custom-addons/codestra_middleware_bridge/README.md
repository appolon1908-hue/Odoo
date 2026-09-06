# Codestra Middleware Bridge

This Odoo 19 add-on is the narrow application boundary between the separate
Codestra Middleware authority and Odoo-owned business records. It does not
implement provider orchestration, expose generic model writes, or connect
directly to PostgreSQL.

The canonical lead command is:

```text
POST /codestra/middleware/v1/commands/crm.lead.upsert
```

The route accepts only the versioned `crm.lead.upsert` command shape, requires a
dedicated single-business-unit service identity, verifies an HMAC signature and
signed identity headers, and enforces tenant-scoped idempotency. The command ID,
idempotency evidence, external mapping, CRM mutation, consent ledger, and hashed
suppression changes commit in one Odoo transaction.

Consent is written to `call.center.consent`. Explicit denial and DNC state are
written to `call.center.suppression` as SHA-256 identifier hashes; plaintext
phone numbers and email addresses are not stored in the suppression table.
Review-pending commands fail closed for contact without fabricating a DNC entry.

Outbound destinations must be credential-free HTTPS URLs. All business writes
remain inside Odoo's ORM and this approved resource-specific service boundary.

## Request signing

The signature is an HMAC-SHA256 over a canonical byte string whose parts are
joined with a single `\n`, in this exact order:

```text
X-Codestra-Timestamp
X-Codestra-Event-ID
HTTP method (uppercase)
request path
X-Tenant-ID
X-Correlation-ID
Idempotency-Key
raw request body (empty for GET)
```

The security headers are inside the signature deliberately: without them a
valid signature over a body could be replayed with swapped identity headers.
The result is sent as `X-Codestra-Signature: sha256=<hex>`.

The signing secret and the service identity are resolved per tenant:

| Purpose | Parameter | Fallback |
| --- | --- | --- |
| Inbound secret | `codestra.middleware.tenant.<tenant>.inbound_hmac_secret` | `codestra.middleware.inbound_hmac_secret` |
| CRM service user | `codestra.middleware.tenant.<tenant>.codestra.crm.service_user_id` | `codestra.crm.service_user_id` |

A tenant must also appear in `codestra.crm.tenant_ids` (comma separated) or be
`codestra.middleware.tenant_id`. Timestamps outside ±300s are rejected.

Global fallback parameters belong only to `codestra.middleware.tenant_id`.
Every additional allowlisted tenant needs its own explicit secret and service
user mapping. Missing tenant configuration fails closed; it cannot borrow the
default tenant's credential or principal. Stored replay responses are returned
only to their original tenant, including when an operator explicitly assigns the
same principal to two tenants. Event IDs remain globally unique; a collision
from another tenant returns `409 replayed_event_id` before any business mutation.

## Reconciliation

```text
GET /codestra/middleware/v1/commands/<command_id>/status
```

Returns the recorded outcome of an earlier command without replaying a write,
for the case where a caller never observed the original response. A timeout is
an unknown outcome: reconcile against this endpoint before retrying.

## Campaign binding

`payload.lead.campaign_code` resolves against `cc.campaign.code`, scoped to the
authorized business unit — not `utm.campaign`. Campaign ownership is immutable
once bound, so changing it on an existing lead returns `409
campaign_binding_immutable`.

## Error contract

| Status | Error | Meaning |
| --- | --- | --- |
| 401 | `invalid_signature` | Bad HMAC, or a secret belonging to another tenant |
| 401 | `expired_timestamp` | Outside the ±300s window |
| 403 | `tenant_rejected` | Tenant not allow-listed |
| 403 | `crm_service_scope_rejected` | Service identity is not scoped to exactly one business unit and company |
| 404 | `command_not_found` | No recorded command with that ID for this tenant |
| 409 | `replayed_event_id` | Event ID already used with different content |
| 409 | `idempotency_conflict` | Same key, different request hash |
| 409 | `stale_command` | Consent older than the stored record |
| 409 | `campaign_binding_immutable` | Attempt to rebind an existing lead's campaign |
| 409 | `mapping_target_missing` | Mapping outlived its lead; reconcile rather than retry |
| 422 | `consent_does_not_permit_contact` | External contact requested without granted consent on a channel |
| 422 | `invalid_lead_subject_value` | Nested value is not a non-empty bounded string |
| 422 | `unknown_campaign` | Campaign code not found in the authorized business unit |

Contact eligibility fails closed: a channel is preferred only where consent was
granted for it. There is no fallback to whatever contact detail exists on the
lead.
