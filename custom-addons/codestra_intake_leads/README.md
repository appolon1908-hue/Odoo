# Codestra Intake Leads

Private Odoo CRM adapter for the unified Codestra intake pipeline.

Canonical path:

`site -> intake SDK -> same-origin BFF -> Caddy -> Kong -> Middleware -> Odoo connector -> crm.lead.codestra_upsert_intake_lead`

This module intentionally exposes no public HTTP controller. Middleware remains the sole cross-system write authority.

The upsert method first protects durable event/idempotency identity per tenant, then attempts to reuse an active lead by normalized email or phone within that tenant. It stores source channel, site, campaign key, attribution, consent, conversation identity and integration metadata on `crm.lead`.

Installation or use in a live environment is not authorized by the repository change. The `ODOO_WRITE` capability and the Middleware connector gates remain authoritative.
