from odoo import api, fields, models
from odoo.exceptions import AccessError


class IntegrationDeadLetter(models.Model):
    _inherit = "codestra.integration.dead.letter"

    name = fields.Char(default="New Dead Letter", required=True)
    reason_code = fields.Char(required=True)
    state = fields.Selection([
        ("open", "Open"), ("investigating", "Investigating"),
        ("resolved", "Resolved"), ("ignored", "Ignored"),
    ], default="open", required=True, index=True)
    first_failed_at = fields.Datetime(default=fields.Datetime.now, required=True)
    last_failed_at = fields.Datetime(default=fields.Datetime.now, required=True)
    attempt_count = fields.Integer(default=0)
    resolution = fields.Char()
    replay_requested = fields.Boolean(default=False)
    replay_requested_at = fields.Datetime()

    @api.model
    def create_for_event(self, event, reason_code, reason):
        return self.create({"name": self.env["ir.sequence"].next_by_code("codestra.integration.dead.letter") or "New Dead Letter",
            "event_id": event.id, "reason_code": reason_code, "reason": reason,
            "payload_json": event.payload_redacted, "attempt_count": event.attempt_count,
            "failed_at": fields.Datetime.now()})

    def request_replay(self):
        self.write({"replay_requested": True, "replay_requested_at": fields.Datetime.now()})
        for record in self:
            self.env["codestra.integration.audit"]._append(record.event_id, "dead_letter.replay_requested", "success", {"dead_letter_id": record.id})
        return True

    def resolve(self, resolution, note=None):
        self.write({"state": "resolved", "resolved": True, "resolution": resolution,
                    "resolution_note": note, "resolved_by": self.env.user.id,
                    "resolved_at": fields.Datetime.now()})
        for record in self:
            self.env["codestra.integration.audit"]._append(record.event_id, "dead_letter.resolved", "success", {"resolution": resolution})
        return True

    def unlink(self):
        raise AccessError("Dead letters cannot be deleted.")
