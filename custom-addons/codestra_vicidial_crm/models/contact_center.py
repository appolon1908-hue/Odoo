from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CallExtension(models.Model):
    _inherit = "codestra.vicidial.call"

    call_answered_at = fields.Datetime()
    ring_seconds = fields.Integer(default=0)
    talk_seconds = fields.Integer(default=0)
    hold_seconds = fields.Integer(default=0)
    recording_reference = fields.Char()
    transfer_count = fields.Integer(default=0)
    transfer_result = fields.Char()
    media_quality_score = fields.Float()

    @api.constrains("uniqueid")
    def _unique_call_guard(self):
        for record in self:
            if record.uniqueid and self.search_count([("uniqueid", "=", record.uniqueid)]) > 1:
                raise ValidationError("A call uniqueid can have only one record.")

    @api.constrains("ring_seconds", "talk_seconds", "hold_seconds", "transfer_count")
    def _nonnegative_contact_center_metrics(self):
        for record in self:
            values = (record.ring_seconds, record.talk_seconds, record.hold_seconds, record.transfer_count)
            if any(value < 0 for value in values):
                raise ValidationError("Call metrics cannot be negative.")


class Callback(models.Model):
    _name = "codestra.callback"
    _description = "Codestra Callback"

    name = fields.Char(required=True)
    # A callback may originate from an appointment/contact before a CRM lead
    # exists.  Keep this optional in the canonical shared callback table; the
    # VICIdial call-control flow still supplies a lead whenever it has one.
    lead_id = fields.Many2one("crm.lead", index=True)
    # Appointment-originated callbacks can be team-owned and can precede the
    # first telephony interaction, so neither legacy reference is physically
    # mandatory in the shared table.
    owner_id = fields.Many2one("res.users")
    call_id = fields.Many2one("codestra.vicidial.call", ondelete="restrict", index=True)
    tenant_id = fields.Char(required=True, index=True)
    vicidial_campaign_id = fields.Many2one(
        "codestra.vicidial.campaign",
        string="VICIdial Campaign",
        ondelete="restrict",
        index=True,
    )
    phone = fields.Char(required=True)
    scheduled_at = fields.Datetime(required=True, index=True)
    timezone = fields.Char(required=True)
    reason = fields.Char(required=True)
    notes = fields.Text()
    priority = fields.Selection(
        [("0", "Low"), ("1", "Normal"), ("2", "High"), ("3", "Urgent")],
        default="1",
        required=True,
        index=True,
    )
    status = fields.Selection(
        [("scheduled", "Scheduled"), ("completed", "Completed"), ("cancelled", "Cancelled")],
        default="scheduled",
        required=True,
    )

    _call_scheduled_unique = models.Constraint(
        "UNIQUE(call_id, scheduled_at)", "The same callback is already scheduled for this call."
    )

    @api.constrains("scheduled_at", "status")
    def _scheduled_callback_is_future(self):
        now = fields.Datetime.now()
        for record in self:
            if record.status == "scheduled" and record.scheduled_at and record.scheduled_at < now:
                raise ValidationError("A scheduled callback must be in the future.")

    def action_reschedule(self, scheduled_at, timezone=None):
        self.ensure_one()
        if self.status != "scheduled":
            raise ValidationError("Only a scheduled callback can be rescheduled.")
        self.write({"scheduled_at": scheduled_at, "timezone": timezone or self.timezone})

    def action_complete(self):
        self.ensure_one()
        if self.status != "scheduled":
            raise ValidationError("Only a scheduled callback can be completed.")
        self.status = "completed"

    def action_cancel(self):
        self.ensure_one()
        if self.status != "scheduled":
            raise ValidationError("Only a scheduled callback can be cancelled.")
        self.status = "cancelled"
