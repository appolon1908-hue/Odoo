"""Idempotently provision the isolated TEST_SYN scraper canary scope."""

from odoo import fields

# ``env`` is injected by the Odoo shell runner.
company = env["res.company"].browse(1).exists()  # noqa: F821
if not company:
    raise RuntimeError("canary company is unavailable")
scoped = env  # noqa: F821
unit = scoped["call.center.business.unit"].search(
    [("code", "=ilike", "web-mobile-ai"), ("company_id", "=", company.id)], limit=1
)
if not unit:
    unit = scoped["call.center.business.unit"].create(
        {
            "name": "Web Mobile AI Synthetic Canary",
            "code": "web-mobile-ai",
            "company_id": company.id,
            "brand": "Codestra",
        }
    )
campaign = scoped["call.center.campaign"].search(
    [("code", "=", "TEST_SYN"), ("business_unit_id", "=", unit.id)], limit=1
)
if not campaign:
    campaign = scoped["call.center.campaign"].create(
        {
            "name": "Synthetic Scraper Certification",
            "code": "TEST_SYN",
            "business_unit_id": unit.id,
            "campaign_type": "sales",
            "direction": "inbound",
            "state": "approved",
            "consent_required": True,
            "dnc_enforced": True,
        }
    )
config = scoped["codestra.lead.automation.config"].search(
    [
        ("environment", "=", "staging"),
        ("business_unit_id", "=", unit.id),
        ("campaign_id", "=", campaign.id),
    ],
    limit=1,
)
values = {
    "business_unit_id": unit.id,
    "campaign_id": campaign.id,
    "environment": "staging",
    "enabled": True,
    "repair_enabled": False,
    "maximum_attempts": 8,
    "lease_seconds": 60,
}
config.write(values) if config else scoped["codestra.lead.automation.config"].create(values)
policy = scoped["codestra.lead.automation.policy"].search(
    [
        ("environment", "=", "staging"),
        ("business_unit_id", "=", unit.id),
        ("campaign_id", "=", campaign.id),
        ("policy_version", "=", "codestra.sales.policy.v1"),
        ("action", "=", "CREATE_LEAD"),
        ("channel", "=", "internal"),
        ("purpose", "=", "synthetic-canary"),
    ],
    limit=1,
)
policy_values = {
    "name": "Synthetic scraper lead creation",
    "business_unit_id": unit.id,
    "campaign_id": campaign.id,
    "environment": "staging",
    "policy_version": "codestra.sales.policy.v1",
    "action": "CREATE_LEAD",
    "channel": "internal",
    "purpose": "synthetic-canary",
    "decision": "ALLOW",
    "requires_consent": True,
    "allowed_fields_csv": "contact_reference",
    "effective_from": fields.Datetime.now(),
    "approved_by_public_id": "CERT-STAGING-AUTOMATION",
    "approval_reference": "SCRAPER-ODOO-CANARY-20260812",
    "active": True,
}
policy.write(policy_values) if policy else scoped["codestra.lead.automation.policy"].create(policy_values)
env.cr.commit()  # noqa: F821
print(f"CANARY_SCOPE_READY company={company.id} unit={unit.id} campaign={campaign.id}")
