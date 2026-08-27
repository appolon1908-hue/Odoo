from odoo import fields, models


class RecordingScopeGroup(models.Model):
    _name = "codestra.vicidial.recording.scope.group"
    _description = "Recording access scope group"

    name = fields.Char(required=True)
    key = fields.Char(required=True, index=True)
    _key_unique = models.Constraint("UNIQUE(key)", "Scope group key must be unique.")


class ResUsers(models.Model):
    _inherit = "res.users"

    recording_scope_group_ids = fields.Many2many(
        "codestra.vicidial.recording.scope.group",
        "recording_scope_group_user_rel",
        "user_id",
        "scope_group_id",
        string="Recording scope groups",
    )
    recording_qa_campaign_ids = fields.Many2many(
        "codestra.vicidial.campaign",
        "recording_qa_campaign_user_rel",
        "user_id",
        "campaign_id",
        string="QA recording campaigns",
    )


class VicidialAgent(models.Model):
    _inherit = "codestra.vicidial.agent"

    recording_scope_group_id = fields.Many2one(
        "codestra.vicidial.recording.scope.group", ondelete="restrict", index=True
    )


class VicidialCall(models.Model):
    _inherit = "codestra.vicidial.call"

    recording_reference_ids = fields.One2many(
        "codestra.vicidial.recording", "call_id", string="Recording references"
    )
    recording_reference_count = fields.Integer(
        compute="_compute_recording_reference_count"
    )

    def _compute_recording_reference_count(self):
        for call in self:
            call.recording_reference_count = len(call.recording_reference_ids)

    def action_recording_references(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Recordings",
            "res_model": "codestra.vicidial.recording",
            "view_mode": "list,form",
            "domain": [("call_id", "=", self.id)],
        }


class VicidialCampaign(models.Model):
    _inherit = "codestra.vicidial.campaign"

    recording_reference_ids = fields.One2many(
        "codestra.vicidial.recording", "campaign_id", string="Recording references"
    )
