from odoo import api, fields, models
from odoo.exceptions import AccessError


class CallEventProjectionPolicy(models.AbstractModel):
    _name = "codestra.call.event.projection.policy"
    _description = "Fail-closed VICIdial call-event projection policy"

    @api.model
    def _parameter_enabled(self, name, default=False):
        raw = self.env["ir.config_parameter"].sudo().get_param(name)
        if raw is None:
            return bool(default)
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}

    @api.model
    def projection_enabled(self):
        return self._parameter_enabled("codestra.call_event_projection_enabled", False)

    @api.model
    def synthetic_only(self):
        return self._parameter_enabled("codestra.call_event_synthetic_only", True)

    @api.model
    def authorize_payload(self, payload):
        if not self.projection_enabled():
            raise AccessError("Call-event projection is disabled.")
        campaign_id = str(payload.get("campaign_id") or "")
        synthetic_test = payload.get("synthetic_test") is True
        if synthetic_test != (campaign_id == "TEST_SYN"):
            raise AccessError("The TEST_SYN campaign and synthetic_test marker must agree.")
        if self.synthetic_only() and not synthetic_test:
            raise AccessError("This environment accepts TEST_SYN call events only.")
        if not self.synthetic_only() and not synthetic_test and not self.env[
            "ir.config_parameter"
        ].sudo().get_param("codestra.call_event_activation_reference"):
            raise AccessError("Non-synthetic call events require an activation reference.")
        return True

    @api.model
    def screen_pop_enabled(self):
        if not self.projection_enabled():
            return False
        flag = self.env["call.center.feature.flag"].sudo().search(
            [("code", "=", "ENABLE_WEBSOCKET_SCREEN_POP")], limit=1
        )
        return bool(flag and flag.enabled)


class VicidialCallProjectionScreenPop(models.Model):
    _inherit = "codestra.vicidial.call"

    def _notify_agent(self):
        self.ensure_one()
        if not self.env["codestra.call.event.projection.policy"].sudo().screen_pop_enabled():
            return False
        return super()._notify_agent()


class CallEventProjectionSettings(models.TransientModel):
    _inherit = "res.config.settings"

    call_event_projection_enabled = fields.Boolean(
        string="VICIdial call-event projection",
        config_parameter="codestra.call_event_projection_enabled",
        default=False,
        help="Accept authenticated lifecycle projections only after staging certification.",
    )
    call_event_synthetic_only = fields.Boolean(
        string="Synthetic call events only",
        config_parameter="codestra.call_event_synthetic_only",
        default=True,
        help="Reject every call event outside the TEST_SYN campaign.",
    )
    call_event_activation_reference = fields.Char(
        string="Call-event activation reference",
        config_parameter="codestra.call_event_activation_reference",
        help="Required for non-synthetic projection. Store an approval ID, never a secret.",
    )
    call_event_service_user_id = fields.Many2one(
        "res.users",
        string="Call-event Middleware service user",
        config_parameter="codestra.call_event.service_user_id",
        help="Dedicated active user holding only the Call Event Projection Service group.",
    )
