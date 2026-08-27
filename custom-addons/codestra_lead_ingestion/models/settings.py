from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    lead_max_upload_mb = fields.Integer(config_parameter="codestra_lead_ingestion.max_upload_mb", default=100)
    lead_max_rows = fields.Integer(config_parameter="codestra_lead_ingestion.max_rows", default=100000)
    lead_preview_limit = fields.Integer(config_parameter="codestra_lead_ingestion.preview_limit", default=10000)
    lead_chunk_size = fields.Integer(config_parameter="codestra_lead_ingestion.chunk_size", default=2000)
    lead_allowed_mime_types = fields.Char(config_parameter="codestra_lead_ingestion.allowed_mime_types", default="text/csv,application/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    lead_retention_days = fields.Integer(config_parameter="codestra_lead_ingestion.retention_days", default=365)
    lead_malware_scanner_enabled = fields.Boolean(config_parameter="codestra_lead_ingestion.malware_scanner_enabled", default=False)
    lead_duplicate_override_enabled = fields.Boolean(config_parameter="codestra_lead_ingestion.duplicate_override_enabled", default=False)
    lead_compliance_approval_required = fields.Boolean(config_parameter="codestra_lead_ingestion.compliance_approval_required", default=True)
    lead_middleware_base_url = fields.Char(config_parameter="codestra_lead_ingestion.middleware_base_url")
    lead_middleware_auth_reference = fields.Char(config_parameter="codestra_lead_ingestion.middleware_auth_reference", help="Opaque secret-store reference only.")
    lead_middleware_publication_enabled = fields.Boolean(config_parameter="codestra_lead_ingestion.middleware_publication_enabled", default=False)
    lead_vicidial_delivery_enabled = fields.Boolean(config_parameter="codestra_lead_ingestion.vicidial_delivery_enabled", default=False)
    lead_vicidial_test_campaign_enabled = fields.Boolean(config_parameter="codestra_lead_ingestion.vicidial_test_campaign_enabled", default=False)
    lead_n8n_enabled = fields.Boolean(config_parameter="codestra_lead_ingestion.n8n_enabled", default=False)
    lead_whatsapp_enabled = fields.Boolean(config_parameter="codestra_lead_ingestion.whatsapp_enabled", default=False)
    lead_email_enabled = fields.Boolean(config_parameter="codestra_lead_ingestion.email_enabled", default=False)
    lead_sms_enabled = fields.Boolean(config_parameter="codestra_lead_ingestion.sms_enabled", default=False)
    lead_emergency_import_enabled = fields.Boolean(config_parameter="codestra_lead_ingestion.emergency_import_enabled", default=False)
    lead_reconciliation_required = fields.Boolean(config_parameter="codestra_lead_ingestion.reconciliation_required", default=True)
    lead_max_retry_count = fields.Integer(config_parameter="codestra_lead_ingestion.max_retry_count", default=5)
    lead_retry_delay_minutes = fields.Integer(config_parameter="codestra_lead_ingestion.retry_delay_minutes", default=5)
