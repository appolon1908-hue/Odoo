# Odoo Rapid Domain + Campaign Onboarding Contract

Odoo is the business authority for campaign creation/activation. When a Codestra-managed campaign is created or activated, Odoo must emit one durable, idempotent synchronization command through the canonical Middleware bridge. Odoo must not write directly to VICIdial databases or provider APIs.

Required campaign fields: tenant_id, business_id, campaign_code, campaign_name, odoo_company_id, odoo_campaign_id, desired_status, timezone, locale, website_domain, lead_source, inbound_group, business_hours, dispositions, callback_policy, recording_policy, script/template references, supervisor/agent scope, transfer targets, consent/DNC policy and capability flags.

Command concept: campaign.sync or equivalent canonical command through codestra_middleware_bridge. Include tenant, correlation ID, idempotency key, expected version/resource version, actor/service identity and audit metadata.

Statuses returned to Odoo: requested, validating, provisioning, synchronized, degraded, reconciliation_required, suspended, retired.

Odoo must record synchronization status/read-back and surface actionable errors. Ambiguous transport outcome requires status reconciliation; never blindly submit a duplicate campaign creation.

Campaign edits and suspension/retirement use the same durable versioned contract. Production dialing remains separately capability-gated and is never enabled solely because campaign synchronization succeeds.
