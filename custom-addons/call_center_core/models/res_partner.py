from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    business_unit_id = fields.Many2one(
        "call.center.business.unit", index=True, tracking=True
    )
    preferred_language_code = fields.Char()
    preferred_contact_method = fields.Selection(
        [
            ("phone", "Phone"),
            ("email", "Email"),
            ("sms", "SMS"),
            ("none", "Do Not Contact"),
        ],
        default="phone",
        tracking=True,
    )
    sensitive_data = fields.Boolean(
        help="Marks records requiring enhanced role-based protection."
    )
