from odoo import fields, models
from odoo.exceptions import AccessError


class CallCenterDuplicateCandidate(models.Model):
    _name = "call.center.duplicate.candidate"
    _description = "Lead Duplicate Candidate"
    _order = "confidence desc, id"

    lead_id = fields.Many2one("crm.lead", required=True, ondelete="cascade", index=True)
    candidate_lead_id = fields.Many2one(
        "crm.lead", required=True, ondelete="cascade", index=True
    )
    business_unit_id = fields.Many2one(
        related="lead_id.business_unit_id", store=True, index=True
    )
    match_reasons = fields.Char(required=True)
    confidence = fields.Float(required=True)
    resolution = fields.Selection(
        [("pending", "Pending"), ("duplicate", "Confirmed Duplicate"),
         ("distinct", "Not a Duplicate"), ("merged", "Merged")],
        default="pending",
        required=True,
    )

    def unlink(self):
        if not (
            self.env.su
            or self.env.user.has_group("call_center_core.group_call_center_manager")
        ):
            raise AccessError("Only managers may remove duplicate candidates.")
        return super().unlink()
