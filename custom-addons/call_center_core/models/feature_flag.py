from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CallCenterFeatureFlag(models.Model):
    _name = "call.center.feature.flag"
    _description = "Authoritative Call Center Feature Flag"
    _order = "code"

    code = fields.Char(required=True, index=True, readonly=True)
    description = fields.Char(required=True)
    enabled = fields.Boolean(default=False)
    environment = fields.Selection(
        [("all", "All"), ("staging", "Staging"), ("production", "Production")],
        default="all",
        required=True,
    )
    activation_reference = fields.Char(
        help="External approval/change reference. Never store a secret here."
    )

    _code_unique = models.Constraint("unique(code)", "Feature-flag codes are unique.")

    @api.constrains("enabled", "environment", "activation_reference")
    def _check_production_activation(self):
        for flag in self:
            if (
                flag.enabled
                and flag.environment in ("all", "production")
                and not flag.activation_reference
            ):
                raise ValidationError(
                    "Production-capable flags require an activation reference."
                )
