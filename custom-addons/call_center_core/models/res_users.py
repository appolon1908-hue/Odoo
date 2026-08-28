from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ResUsers(models.Model):
    _inherit = "res.users"

    call_center_business_unit_ids = fields.Many2many(
        "call.center.business.unit",
        "call_center_business_unit_user_rel",
        "user_id",
        "business_unit_id",
        string="Authorized Call Center Business Units",
    )
    call_center_default_business_unit_id = fields.Many2one(
        "call.center.business.unit", string="Default Call Center Business Unit"
    )
    call_center_department_ids = fields.Many2many(
        "call.center.department", string="Call Center Departments"
    )
    call_center_supervisor_id = fields.Many2one(
        "res.users", string="Call Center Supervisor"
    )
    call_center_primary_role = fields.Selection(
        [
            ("non_operational", "Non-Operational"),
            ("platform_superuser", "Platform Superuser"),
            ("global_administrator", "Global Administrator"),
            ("business_unit_director", "Business Unit Director"),
            ("department_manager", "Department Manager"),
            ("campaign_manager", "Campaign Manager"),
            ("supervisor", "Supervisor"),
            ("team_leader", "Team Leader"),
            ("senior_agent", "Senior Agent"),
            ("agent", "Agent"),
            ("junior_agent", "Junior Agent"),
            ("trainee", "Trainee"),
            ("sdr", "SDR"),
            ("closer", "Closer"),
            ("transfer_coordinator", "Transfer Coordinator"),
            ("support_agent", "Support Agent"),
            ("fulfillment_agent", "Fulfillment Agent"),
            ("retention_agent", "Retention Agent"),
            ("upsell_agent", "Upsell Agent"),
            ("qa_analyst", "QA Analyst"),
            ("compliance_reviewer", "Compliance Reviewer"),
            ("auditor", "Auditor"),
            ("integration_service", "Integration Service Account"),
            ("workforce_analyst", "Workforce Analyst"),
            ("trainer", "Trainer"),
        ],
        default="non_operational",
        required=True,
        help=(
            "Primary functional classification only. Authorization is granted "
            "through security groups, never by this value."
        ),
    )
    call_center_secondary_roles = fields.Char(
        help="Comma-separated role codes. Authorization still requires security groups."
    )
    call_center_language_codes = fields.Char(default="en")

    @api.constrains(
        "call_center_business_unit_ids", "call_center_default_business_unit_id"
    )
    def _check_default_business_unit(self):
        for user in self:
            default = user.call_center_default_business_unit_id
            if default and default not in user.call_center_business_unit_ids:
                raise ValidationError(
                    "The default business unit must be one of the authorized units."
                )
