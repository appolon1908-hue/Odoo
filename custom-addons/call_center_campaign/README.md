# Call Center Campaign

This Odoo 19 add-on owns campaign, team, script, lifecycle, transactional-outbox
and integration-result models used by the Codestra call-center platform.

## Boundaries

- Odoo remains the business system of record.
- Cross-system delivery is performed through the Codestra middleware contract.
- The add-on never opens a separate PostgreSQL connection or exposes database
  credentials.
- Local cursor SQL is limited to reviewed row-locking, readiness and read-only
  projection operations declared against the exact module tree.
- Odoo never writes directly to VICIdial tables or activates n8n workflows.

## Automatic campaign design

Normal user and API campaign creation now defaults to automatic design management.
Odoo assigns an immutable integration UUID, creates one transactional
`campaign.design.requested.v1` event per revision and retains immutable preview
history. Installation, import and reviewed migration flows can opt out explicitly
without weakening the normal creation path.

A design can be approved only after Middleware returns the complete current
manifest, Odoo verifies its canonical SHA-256 hash, business-unit list range,
campaign-owned identifiers, policy binding and n8n scope, all validation errors
are resolved, every live feature flag remains false and an audit reason is
recorded. Approval writes an idempotent `campaign.approved.v1` event; it does not
provision or activate external resources.

See `AUTOMATIC_CAMPAIGN_PROVISIONING.md` at the repository root and
`docs/AUTOMATIC_PROVISIONING.md` in this add-on.

## Safety

Campaign fixtures and automation definitions install inactive. External delivery,
callbacks, email, SMS and dialing remain fail-closed until their independent
production gates are approved.

## Verification

Run the module tests together with `scripts/run_ci.sh`; the canonical baseline and
integration-boundary validators reject undeclared tree drift or SQL/import
exceptions.

## Preview queue upgrade (19.0.5.3.4)

Configure `CODESTRA_MIDDLEWARE_CAMPAIGN_TENANTS` with an explicit JSON mapping
from each business-unit code to its authorized Middleware tenant. Missing or
invalid endpoint, token-file or tenant configuration defers delivery for sixty
seconds without consuming the five-attempt delivery budget. Correcting the
configuration lets the same immutable event resume automatically. Actual
transport/response failures retain the existing backoff and dead-letter limit.

Run the module upgrade with delivery workers stopped. Reconcile any processing
legacy previews first; the upgrade fails atomically if one remains. The upgrade
preserves old payloads, hashes and idempotency keys, marks undelivered previews
without `design_request_revision` as superseded, and creates a fresh revision
only when the current requested design needs replacement. Older queued events
cannot overwrite a newer valid request. Delivered events remain unchanged.
Repeated upgrades create no duplicate successors. The new revision requires its
own preview and approval; this upgrade does not activate a campaign or contact
Middleware. Both automatic and explicitly unmanaged producers now bind the
revision before computing the payload hash.

The Odoo/PostgreSQL regression suite exercises the migration entrypoint,
immutable history, repeat execution, rollback, processing-event refusal and
configuration recovery through the delivery cron.
