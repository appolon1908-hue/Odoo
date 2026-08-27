from odoo import api, fields, models
from odoo.exceptions import ValidationError


class IntegrationEndpoint(models.Model):
    _name = "codestra.integration.endpoint"
    _description = "Codestra Logical Integration Endpoint Reference"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    endpoint_type = fields.Selection([("middleware", "Middleware"), ("orchestrator", "Orchestrator"), ("logical", "Logical")], default="logical", required=True)
    direction = fields.Selection([("inbound", "Inbound"), ("outbound", "Outbound"), ("bidirectional", "Bidirectional")], required=True)
    base_url_reference = fields.Char()
    enabled = fields.Boolean(default=False)
    test_only = fields.Boolean(default=True)
    allowed_event_types = fields.Text()
    timeout_seconds = fields.Integer(default=10)
    max_payload_bytes = fields.Integer(default=65536)
    notes = fields.Text()

    _code_unique = models.Constraint("UNIQUE(code)", "Endpoint code must be unique.")
    _limits_positive = models.Constraint(
        "CHECK(timeout_seconds > 0 AND max_payload_bytes > 0)",
        "Endpoint limits must be positive.",
    )

    @api.constrains("base_url_reference")
    def _check_safe_reference(self):
        for record in self:
            value = record.base_url_reference or ""
            authority = value.split("://", 1)[-1].split("/", 1)[0]
            if "@" in authority or "?" in value:
                raise ValidationError("URL references cannot contain credentials or query strings.")

    @api.model
    def perform_connectivity_test(self, *args, **kwargs):
        raise ValidationError("Connectivity tests and external delivery are disabled.")
