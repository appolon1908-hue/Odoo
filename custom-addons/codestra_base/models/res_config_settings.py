from odoo import api, fields, models


FLAG_NAMES = (
    "live_writes_enabled", "vicidial_read_enabled", "vicidial_write_enabled",
    "odoo_sync_enabled", "n8n_delivery_enabled", "agent_api_read_enabled",
    "agent_api_write_enabled", "call_control_enabled", "transfer_control_enabled",
    "recording_access_enabled", "ai_advisory_enabled", "ai_external_delivery_enabled",
)


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    live_writes_enabled = fields.Boolean(string="Live writes (disabled by default)")
    vicidial_read_enabled = fields.Boolean(string="VICIdial reads (disabled by default)")
    vicidial_write_enabled = fields.Boolean(string="VICIdial writes (disabled by default)")
    odoo_sync_enabled = fields.Boolean(string="Odoo synchronization (disabled by default)")
    n8n_delivery_enabled = fields.Boolean(string="n8n delivery (disabled by default)")
    agent_api_read_enabled = fields.Boolean(string="Agent API reads (disabled by default)")
    agent_api_write_enabled = fields.Boolean(string="Agent API writes (disabled by default)")
    call_control_enabled = fields.Boolean(string="Call control (disabled by default)")
    transfer_control_enabled = fields.Boolean(string="Transfer control (disabled by default)")
    recording_access_enabled = fields.Boolean(string="Recording access (disabled by default)")
    ai_advisory_enabled = fields.Boolean(string="AI advisory (disabled by default)")
    ai_external_delivery_enabled = fields.Boolean(string="External AI delivery (disabled by default)")

    def get_values(self):
        values = super().get_values()
        params = self.env["ir.config_parameter"].sudo()
        values.update({name: self._safe_bool(params.get_param(f"codestra.{name}", default="false")) for name in FLAG_NAMES})
        return values

    def set_values(self):
        super().set_values()
        params = self.env["ir.config_parameter"].sudo()
        for name in FLAG_NAMES:
            params.set_param(f"codestra.{name}", "true" if getattr(self, name) else "false")

    @staticmethod
    def _safe_bool(value):
        return str(value).strip().lower() == "true"


class CodestraFeatureFlags(models.AbstractModel):
    _name = "codestra.feature.flags"
    _description = "Codestra fail-closed feature flag reader"
    _abstract = True

    @api.model
    def flag_enabled(self, name):
        if name not in FLAG_NAMES:
            return False
        value = self.env["ir.config_parameter"].sudo().get_param(f"codestra.{name}", default="false")
        return ResConfigSettings._safe_bool(value)
