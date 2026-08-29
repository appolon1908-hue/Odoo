from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


class IntegrationDelivery(models.Model):
    _name = "codestra.integration.delivery"
    _description = "Codestra Integration Delivery Attempt Ledger"
    _order = "started_at desc, id desc"

    event_id = fields.Many2one("codestra.integration.event", required=True, ondelete="restrict", index=True)
    attempt_number = fields.Integer(required=True)
    state = fields.Selection([
        ("pending", "Pending"), ("processing", "Processing"),
        ("succeeded", "Succeeded"), ("failed", "Failed"),
        ("abandoned", "Abandoned"),
    ], default="pending", required=True, index=True)
    destination = fields.Char(required=True, index=True)
    started_at = fields.Datetime()
    finished_at = fields.Datetime()
    duration_ms = fields.Integer()
    response_status = fields.Integer()
    response_reference = fields.Char()
    error_code = fields.Char()
    error_message = fields.Text()
    request_hash = fields.Char(index=True)
    response_hash = fields.Char(index=True)
    correlation_id = fields.Char(index=True)

    _attempt_positive = models.Constraint("CHECK(attempt_number > 0)", "Attempt number must be positive.")
    _duration_nonnegative = models.Constraint(
        "CHECK(duration_ms IS NULL OR duration_ms >= 0)", "Duration cannot be negative."
    )
    _attempt_unique = models.Constraint(
        "UNIQUE(event_id, attempt_number)", "Attempt number already exists for this event."
    )

    def unlink(self):
        if not self.env.is_superuser():
            raise AccessError("Delivery-attempt history cannot be deleted.")
        return super().unlink()

    @api.model
    def perform_delivery(self, *args, **kwargs):
        raise ValidationError("External delivery is disabled; middleware owns transport.")
