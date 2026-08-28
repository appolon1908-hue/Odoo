from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"
    keycloak_subject = fields.Char(index=True, copy=False)
    codestra_tenant_id = fields.Char(index=True)
    vicidial_agent_id = fields.Many2one("codestra.vicidial.agent", ondelete="set null")
    vicidial_username = fields.Char(index=True)
    call_center_role = fields.Selection(
        [
            ("agent", "Agent"),
            ("senior_agent", "Senior agent"),
            ("closer", "Closer"),
            ("supervisor", "Supervisor"),
            ("manager", "Manager"),
            ("administrator", "Administrator"),
            ("integration_service", "Integration service"),
        ],
        default="agent",
    )
    allowed_campaign_ids = fields.Many2many("codestra.vicidial.campaign")
    transfer_permission_level = fields.Selection(
        [("none", "None"), ("supervised", "Supervised"), ("full", "Full")], default="none"
    )
    can_monitor_calls = fields.Boolean()
    can_barge_calls = fields.Boolean()
    can_view_recordings = fields.Boolean()

    _keycloak_subject_unique = models.Constraint(
        "UNIQUE(keycloak_subject)", "A Keycloak subject may identify only one Odoo user."
    )
