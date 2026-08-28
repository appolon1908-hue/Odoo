from odoo import fields, models
from odoo.tools.sql import column_exists


def _default_business_unit(self):
    """Avoid reading a res.users column before registry upgrade creates it."""
    if not column_exists(
        self.env.cr, "res_users", "call_center_default_business_unit_id"
    ):
        return False
    return (
        self.env.user.call_center_default_business_unit_id
        or self.env.ref(
            "call_center_core.business_unit_shared", raise_if_not_found=False
        )
    )


class CrmLead(models.Model):
    _inherit = "crm.lead"

    business_unit_id = fields.Many2one(
        "call.center.business.unit",
        required=True,
        index=True,
        tracking=True,
        default=_default_business_unit,
    )
    assigned_closer_id = fields.Many2one("res.users", tracking=True)
    integration_uuid = fields.Char(
        index=True,
        copy=False,
        help="Stable public identifier used by Codestra integration endpoints.",
    )
    external_source_id = fields.Char(index=True, copy=False)
    source_detail = fields.Char()
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
    preferred_contact_time = fields.Char()
    next_action_summary = fields.Char(tracking=True)
