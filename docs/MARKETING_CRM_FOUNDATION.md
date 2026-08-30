# Marketing CRM Implementation Foundation

Odoo is the authoritative business record for lead/contact/opportunity state and revenue outcome.

## Required lead fields
- external_lead_id
- tenant_id
- campaign_id
- source_platform
- source_account_id
- source_campaign_id
- source_adset_id
- source_ad_id
- source
- medium
- landing_page_id
- correlation_id
- attribution_version
- first_touch_at / last_touch_at
- consent_status
- qualification_state

This checklist is subordinate to the complete canonical data contract in `MARKETING-CRM-SYSTEM-OF-RECORD-CONTRACT.md`; where that contract requires additional context, implementations must preserve it.

## Required opportunity feedback
Marketing receives normalized lifecycle feedback with stable identity and scope: external_lead_id and/or external_opportunity_id, tenant_id, campaign_id where available, correlation_id, qualified, appointment_booked, proposal_sent, won, lost, revenue_minor, currency, occurred_at, and attribution_version where available.

## Isolation
Campaign-scoped agents and supervisors must remain isolated to their assigned campaign. Marketing synchronization must never broaden Odoo record rules or expose another campaign's leads.

## Integration
Writes arrive through authenticated service APIs/Middleware with idempotency keys. Odoo publishes cross-system effects through its transactional outbox to Middleware. Odoo does not call advertising-provider APIs or n8n directly.
