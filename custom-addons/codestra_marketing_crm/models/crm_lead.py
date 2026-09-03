from odoo import fields, models

class CrmLead(models.Model):
    _inherit = "crm.lead"

    codestra_marketing_tenant_id = fields.Char(index=True, copy=False)
    codestra_marketing_lead_id = fields.Char(index=True, copy=False)
    codestra_provider = fields.Selection([
        ("meta", "Meta"),
        ("google", "Google"),
        ("linkedin", "LinkedIn"),
        ("tiktok", "TikTok"),
        ("organic", "Organic"),
        ("other", "Other"),
    ], index=True, copy=False)
    codestra_provider_campaign_id = fields.Char(index=True, copy=False)
    codestra_provider_adset_id = fields.Char(index=True, copy=False)
    codestra_provider_ad_id = fields.Char(index=True, copy=False)
    codestra_click_id = fields.Char(index=True, copy=False)
    codestra_landing_page = fields.Char(copy=False)
    codestra_first_touch_at = fields.Datetime(copy=False)
    codestra_last_touch_at = fields.Datetime(copy=False)
    codestra_conversion_synced_at = fields.Datetime(copy=False, readonly=True)
    codestra_conversion_status = fields.Selection([
        ("not_ready", "Not Ready"),
        ("queued", "Queued"),
        ("synced", "Synced"),
        ("failed", "Failed"),
    ], default="not_ready", index=True, copy=False, readonly=True)
    codestra_integration_idempotency_key = fields.Char(index=True, copy=False, readonly=True)

    _sql_constraints = [
        (
            "codestra_marketing_lead_unique",
            "unique(codestra_marketing_tenant_id, codestra_marketing_lead_id)",
            "The Codestra marketing lead ID must be unique within a tenant.",
        )
    ]
