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
- landing_page_id
- first_touch_at / last_touch_at
- consent_status
- qualification_state

## Required opportunity feedback
Marketing receives normalized lifecycle feedback only: qualified, appointment_booked, proposal_sent, won, lost, revenue_minor, currency, occurred_at.

## Isolation
Campaign-scoped agents and supervisors must remain isolated to their assigned campaign. Marketing synchronization must never broaden Odoo record rules or expose another campaign's leads.

## Integration
Writes arrive through authenticated service APIs/Middleware with idempotency keys. Odoo does not call advertising-provider APIs directly.
