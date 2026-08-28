from odoo import fields, models


class IntegrationSettings(models.TransientModel):
    _inherit = "res.config.settings"
    middleware_base_url = fields.Char(config_parameter="codestra.middleware_base_url")
    # Store only a secret reference supplied by the deployment environment.
    webhook_shared_secret = fields.Char(config_parameter="codestra.webhook_secret")
    vicidial_read_only = fields.Boolean(config_parameter="codestra.vicidial_read_only", default=True)
    live_writes_enabled = fields.Boolean(config_parameter="codestra.live_writes_enabled", default=False)
    odoo_write_enabled = fields.Boolean(config_parameter="codestra.odoo_write_enabled", default=False)
    n8n_delivery_enabled = fields.Boolean(config_parameter="codestra.n8n_delivery_enabled", default=False)
    call_control_enabled = fields.Boolean(config_parameter="codestra.call_control_enabled", default=False)
    transfer_control_enabled = fields.Boolean(config_parameter="codestra.transfer_control_enabled", default=False)
    request_timeout_seconds = fields.Integer(config_parameter="codestra.request_timeout_seconds", default=10)
    max_retry_count = fields.Integer(config_parameter="codestra.max_retry_count", default=5)
    retry_delay_seconds = fields.Integer(config_parameter="codestra.retry_delay_seconds", default=60)
    webhook_allowed_cidrs = fields.Char(config_parameter="codestra.webhook_allowed_cidrs")
    recording_access_enabled = fields.Boolean(config_parameter="codestra.recording_access_enabled", default=False)
