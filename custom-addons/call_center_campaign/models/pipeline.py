from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CallCenterPipeline(models.Model):
    _name = "call.center.pipeline"
    _description = "Business Unit CRM Pipeline"
    _inherit = ["mail.thread", "call.center.business.unit.mixin"]
    _order = "business_unit_id, name"

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    stage_flow = fields.Text(required=True)
    stage_ids = fields.Many2many("crm.stage", string="CRM Stages")

    _code_unit_unique = models.Constraint(
        "unique(code, business_unit_id)",
        "Pipeline codes must be unique within a business unit.",
    )


class CallCenterBusinessUnit(models.Model):
    _inherit = "call.center.business.unit"

    default_pipeline_id = fields.Many2one(
        "call.center.pipeline", ondelete="restrict", tracking=True
    )
    default_inbound_campaign_id = fields.Many2one(
        "call.center.campaign", ondelete="restrict", tracking=True
    )
    default_outbound_campaign_id = fields.Many2one(
        "call.center.campaign", ondelete="restrict", tracking=True
    )

    @api.constrains(
        "default_pipeline_id",
        "default_inbound_campaign_id",
        "default_outbound_campaign_id",
    )
    def _check_campaign_defaults_scope(self):
        for unit in self:
            for record in filter(
                None,
                (
                    unit.default_pipeline_id,
                    unit.default_inbound_campaign_id,
                    unit.default_outbound_campaign_id,
                ),
            ):
                if record.business_unit_id != unit:
                    raise ValidationError(
                        "Pipeline and campaign defaults must belong to the unit."
                    )
