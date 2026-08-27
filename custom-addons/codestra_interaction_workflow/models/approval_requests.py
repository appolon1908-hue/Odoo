from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


class CodestraIntegrationRetryRequest(models.Model):
    _name = "codestra.integration.retry.request"
    _description = "Integration Retry Approval Request"
    _order = "create_date desc"

    delivery_id = fields.Char(required=True, index=True, readonly=True)
    correlation_id = fields.Char(required=True, index=True, readonly=True)
    reason = fields.Text(required=True, readonly=True)
    requested_by = fields.Many2one("res.users", required=True, readonly=True)
    state = fields.Selection(
        [("pending_approval", "Pending approval"), ("approved", "Approved"), ("rejected", "Rejected")],
        default="pending_approval",
        required=True,
        readonly=True,
    )

    @api.model
    def create(self, vals):
        if not self.env.user.has_group("call_center_core.group_call_center_manager"):
            raise AccessError("Only integration supervisors may request retries.")
        return super().create(vals)


class CodestraIntegrationActivationRequest(models.Model):
    _name = "codestra.integration.activation.request"
    _description = "Integration Activation Approval Request"
    _order = "create_date desc"

    workflow_key = fields.Char(required=True, index=True, readonly=True)
    workflow_version = fields.Char(required=True, readonly=True)
    environment = fields.Selection(
        [("TEST", "Test"), ("STAGING", "Staging"), ("PRODUCTION", "Production")],
        required=True,
        readonly=True,
    )
    reason = fields.Text(required=True, readonly=True)
    requested_by = fields.Many2one("res.users", required=True, readonly=True)
    state = fields.Selection(
        [("pending_approval", "Pending approval"), ("approved", "Approved"), ("rejected", "Rejected")],
        default="pending_approval",
        required=True,
        readonly=True,
    )

    @api.model
    def create(self, vals):
        if not self.env.user.has_group("call_center_core.group_call_center_manager"):
            raise AccessError("Only integration supervisors may request activation.")
        if vals.get("environment") == "PRODUCTION":
            raise ValidationError("Production activation requests are disabled in this addon.")
        return super().create(vals)
