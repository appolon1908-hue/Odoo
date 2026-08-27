from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class CodestraCase(models.Model):
    _name = "codestra.case"
    _description = "Codestra Operational Case"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "priority desc, opened_at desc, id desc"
    _check_company_auto = True

    _ALLOWED_TRANSITIONS = {
        "new": {"in_progress", "cancelled"},
        "in_progress": {"escalated", "resolved", "cancelled"},
        "escalated": {"in_progress", "resolved", "cancelled"},
        "resolved": {"in_progress", "closed"},
        "closed": {"in_progress"},
        "cancelled": {"in_progress"},
    }

    name = fields.Char(
        string="Case Number",
        required=True,
        readonly=True,
        copy=False,
        index=True,
        default=lambda self: _("New"),
        tracking=True,
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        index=True,
        default=lambda self: self.env.company,
    )
    partner_id = fields.Many2one("res.partner", string="Customer", index=True, tracking=True)
    lead_id = fields.Many2one(
        "crm.lead",
        string="Lead / Opportunity",
        index=True,
        tracking=True,
        check_company=True,
    )
    campaign_id = fields.Many2one(
        "codestra.vicidial.campaign",
        string="Campaign",
        index=True,
        tracking=True,
        help="Authorized campaign reference. Legacy campaign records are tenant-scoped by their integration mapping.",
    )
    call_id = fields.Many2one(
        "codestra.vicidial.call",
        string="Call",
        index=True,
        tracking=True,
        help="Controlled call reference. Recording content is not stored on this case.",
    )
    category = fields.Selection(
        [
            ("complaint", "Complaint"),
            ("dispute", "Dispute"),
            ("refund", "Refund Review"),
            ("incident", "Incident"),
            ("executive", "Executive Escalation"),
        ],
        required=True,
        default="complaint",
        index=True,
        tracking=True,
    )
    priority = fields.Selection(
        [("0", "Low"), ("1", "Normal"), ("2", "High"), ("3", "Urgent")],
        required=True,
        default="1",
        index=True,
        tracking=True,
    )
    state = fields.Selection(
        [
            ("new", "New"),
            ("in_progress", "In Progress"),
            ("escalated", "Escalated"),
            ("resolved", "Resolved"),
            ("closed", "Closed"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="new",
        index=True,
        tracking=True,
        copy=False,
    )
    owner_id = fields.Many2one(
        "res.users",
        string="Owner",
        required=True,
        default=lambda self: self.env.user,
        index=True,
        tracking=True,
    )
    opened_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True, copy=False)
    due_at = fields.Datetime(index=True, tracking=True)
    closed_at = fields.Datetime(readonly=True, index=True, copy=False)
    summary = fields.Char(required=True, tracking=True)
    description = fields.Text()
    resolution = fields.Text(tracking=True)
    escalation_reason = fields.Text(tracking=True)
    evidence_reference = fields.Char(
        help="Controlled evidence identifier only. Do not store credentials or raw secret URLs."
    )

    @api.model_create_multi
    def create(self, values_list):
        sequence = self.env["ir.sequence"]
        for values in values_list:
            if values.get("name", _("New")) == _("New"):
                values["name"] = sequence.next_by_code("codestra.case") or _("New")
        return super().create(values_list)

    @api.constrains("opened_at", "due_at")
    def _check_due_at(self):
        for record in self:
            if record.opened_at and record.due_at and record.due_at < record.opened_at:
                raise ValidationError(_("The case due time cannot precede its opening time."))

    @api.constrains("state", "resolution")
    def _check_resolution(self):
        for record in self:
            if record.state in {"resolved", "closed"} and not (record.resolution or "").strip():
                raise ValidationError(_("Resolved and closed cases require a resolution."))

    def _transition(self, target):
        for record in self:
            source = record.state
            if target not in self._ALLOWED_TRANSITIONS.get(source, set()):
                raise UserError(_("The transition from %s to %s is not permitted.") % (source, target))
            values = {"state": target}
            if target in {"closed", "cancelled"}:
                values["closed_at"] = fields.Datetime.now()
            elif source in {"closed", "cancelled"}:
                values["closed_at"] = False
            record.write(values)
            record.message_post(body=_("Case state changed from %s to %s.") % (source, target))
        return True

    def action_start(self):
        return self._transition("in_progress")

    def action_escalate(self):
        for record in self:
            if not (record.escalation_reason or "").strip():
                raise ValidationError(_("An escalation reason is required."))
        return self._transition("escalated")

    def action_resolve(self):
        for record in self:
            if not (record.resolution or "").strip():
                raise ValidationError(_("A resolution is required."))
        return self._transition("resolved")

    def action_close(self):
        return self._transition("closed")

    def action_cancel(self):
        return self._transition("cancelled")

    def action_reopen(self):
        return self._transition("in_progress")

    def unlink(self):
        if any(record.state not in {"new", "cancelled"} for record in self):
            raise UserError(_("Only new or cancelled cases may be deleted."))
        return super().unlink()
