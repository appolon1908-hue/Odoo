from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CallCenterScript(models.Model):
    _name = "call.center.script"
    _description = "Versioned Call Script"
    _inherit = ["mail.thread", "call.center.business.unit.mixin"]
    _order = "campaign_id, effective_date desc, version desc"

    name = fields.Char(required=True)
    campaign_id = fields.Many2one(
        "call.center.campaign", required=True, ondelete="cascade", index=True
    )
    language_code = fields.Char(required=True, default="en")
    version = fields.Char(required=True)
    effective_date = fields.Date()
    state = fields.Selection(
        [("draft", "Draft"), ("review", "In Review"), ("approved", "Approved"),
         ("retired", "Retired")],
        default="draft",
        required=True,
        tracking=True,
    )
    approved_by_id = fields.Many2one("res.users", readonly=True)
    approved_at = fields.Datetime(readonly=True)
    opening = fields.Html()
    identity_verification = fields.Html()
    ai_disclosure = fields.Html()
    recording_disclosure = fields.Html()
    qualification_questions = fields.Html()
    product_explanation = fields.Html()
    objection_handling = fields.Html()
    pricing_guidance = fields.Html()
    closing = fields.Html()
    required_legal_statements = fields.Html()
    opt_out_language = fields.Html()
    escalation_instructions = fields.Html()
    prohibited_statements = fields.Html()
    supervisor_notes = fields.Html()

    _version_unique = models.Constraint(
        "unique(campaign_id, language_code, version)",
        "Script versions must be unique per campaign and language.",
    )

    @api.constrains("business_unit_id", "campaign_id")
    def _check_campaign_unit(self):
        for script in self:
            if script.business_unit_id != script.campaign_id.business_unit_id:
                raise ValidationError("Script and campaign business units must match.")

    def action_approve(self):
        self.ensure_one()
        if not self.env.user.has_group("call_center_core.group_call_center_manager"):
            raise ValidationError("Only campaign managers may approve scripts.")
        self.write(
            {"state": "approved", "approved_by_id": self.env.user.id,
             "approved_at": fields.Datetime.now()}
        )
