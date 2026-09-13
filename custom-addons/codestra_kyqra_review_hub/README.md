# Codestra Kyqra Review Hub

This addon is the Odoo review projection for the canonical Kyqra crawler
completion event.

The integration boundary is:

    Kyqra -> signed POST /api/v1/kyqra/results -> Middleware durable inbox -> Odoo review hub

The addon exposes the governed model method
codestra.kyqra.batch.apply_middleware_event for the Middleware Odoo adapter.
It creates an immutable batch, entity projections, and evidence records. All
records remain review_pending until an Odoo reviewer explicitly approves or
rejects them.

The addon deliberately does not create crm.lead, res.partner, contacts,
activities, campaigns, provider calls, or external messages. A reviewed
projection is not consent to contact and approval never enables external
delivery.

Middleware remains the only cross-system write authority. Kyqra does not call
Odoo directly.

## Fail-closed service binding

The projection method requires the dedicated Kyqra Middleware Service group and
a tenant-specific configuration:

    codestra.kyqra.tenant_ids=tenant-1,tenant-2
    codestra.middleware.tenant.<tenant>.codestra.kyqra.service_user_id=<user id>
    codestra.kyqra.tenant.<tenant>.company_id=<company id>

Missing or malformed bindings reject the event. The addon is disabled by
default because installation does not grant the service group or configure any
tenant.

## Contract

Accepted events use event version 1.0, source kyqra-gateway, and event types
codestra.crawler.job.completed or codestra.crawler.result.review_required.
Every result must carry review_required=true, an HTTPS source URL, a data object,
provenance, and a capture method. External contact remains false.
