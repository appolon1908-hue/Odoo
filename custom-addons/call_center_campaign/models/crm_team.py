from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CrmTeam(models.Model):
    _inherit = "crm.team"

    business_unit_id = fields.Many2one(
        "call.center.business.unit", index=True, tracking=True
    )
    shared_business_unit_ids = fields.Many2many(
        "call.center.business.unit",
        "crm_team_shared_business_unit_rel",
        string="Explicitly Shared With",
    )
    is_primary_business_unit_team = fields.Boolean(default=False, tracking=True)
    leader_role = fields.Char(required=True, default="Business Unit Director")
    default_campaign_id = fields.Many2one(
        "call.center.campaign", ondelete="restrict", tracking=True
    )
    default_pipeline_id = fields.Many2one(
        "call.center.pipeline", ondelete="restrict", tracking=True
    )
    monthly_sales_target = fields.Monetary(currency_field="currency_id")
    monthly_invoice_target = fields.Monetary(currency_field="currency_id")
    monthly_lead_target = fields.Integer()
    monthly_conversion_target = fields.Float(
        help="Target percentage from 0 through 100."
    )
    default_language_id = fields.Many2one(
        "res.lang", default=lambda self: self.env.ref("base.lang_en")
    )
    vicidial_user_group = fields.Char(index=True)
    default_inbound_group = fields.Char()
    default_outbound_campaign = fields.Char()

    @api.constrains(
        "business_unit_id",
        "shared_business_unit_ids",
        "default_campaign_id",
        "default_pipeline_id",
        "monthly_conversion_target",
    )
    def _check_team_scope(self):
        for team in self:
            if team.is_primary_business_unit_team and not team.business_unit_id:
                raise ValidationError(
                    "A primary call-center CRM team requires a business unit."
                )
            if team.business_unit_id in team.shared_business_unit_ids:
                raise ValidationError(
                    "A team cannot share explicitly with its owning business unit."
                )
            for record in filter(
                None, (team.default_campaign_id, team.default_pipeline_id)
            ):
                if record.business_unit_id != team.business_unit_id:
                    raise ValidationError(
                        "Team defaults must belong to the team's business unit."
                    )
            if not 0 <= team.monthly_conversion_target <= 100:
                raise ValidationError(
                    "Monthly conversion target must be between 0 and 100."
                )

    @api.constrains("business_unit_id", "is_primary_business_unit_team")
    def _check_one_primary_team(self):
        for team in self.filtered("is_primary_business_unit_team"):
            duplicate = self.search_count(
                [
                    ("id", "!=", team.id),
                    ("business_unit_id", "=", team.business_unit_id.id),
                    ("is_primary_business_unit_team", "=", True),
                ]
            )
            if duplicate:
                raise ValidationError(
                    "A business unit may have only one primary CRM team."
                )

    def _alias_get_creation_values(self):
        values = super()._alias_get_creation_values()
        if self and self.business_unit_id:
            defaults = values.setdefault("alias_defaults", {})
            defaults["business_unit_id"] = self.business_unit_id.id
            if self.default_campaign_id:
                defaults["call_center_campaign_id"] = self.default_campaign_id.id
        return values


class ResUsers(models.Model):
    _inherit = "res.users"

    call_center_team_ids = fields.Many2many(
        "call.center.team", string="Call Center Teams"
    )
    call_center_campaign_ids = fields.Many2many(
        "call.center.campaign", string="Authorized Call Center Campaigns"
    )
