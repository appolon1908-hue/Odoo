from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


class CallWorkspaceCall(models.Model):
    _inherit = "codestra.vicidial.call"

    connected_at = fields.Datetime(copy=False)
    opportunity_id = fields.Many2one("crm.lead", domain="[('type','=','opportunity')]", index=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, index=True)
    sub_disposition_id = fields.Many2one("codestra.call.sub.disposition", ondelete="restrict")
    callback_at = fields.Datetime(index=True)
    callback_owner_id = fields.Many2one("res.users", ondelete="restrict")
    wrap_up_started_at = fields.Datetime(copy=False)
    wrap_up_completed_at = fields.Datetime(copy=False)
    wrap_up_seconds = fields.Integer(default=0, copy=False)
    note_ids = fields.One2many("codestra.call.note", "call_id")
    qa_review_ids = fields.One2many("codestra.call.qa.review", "call_id")

    _workspace_durations_nonnegative = models.Constraint(
        "CHECK(wrap_up_seconds >= 0)", "Wrap-up duration cannot be negative."
    )


class CallWorkspaceEvent(models.Model):
    _inherit = "codestra.vicidial.call.event"

    source = fields.Char(default="middleware", index=True)
    actor_id = fields.Many2one("res.users", ondelete="set null", index=True)
    sequence = fields.Integer(default=0, index=True)


class CallNote(models.Model):
    _name = "codestra.call.note"
    _description = "Call workspace note"
    _order = "write_date desc, id desc"

    call_id = fields.Many2one("codestra.vicidial.call", required=True, ondelete="restrict", index=True)
    tenant_id = fields.Char(related="call_id.tenant_id", store=True, index=True)
    contact_id = fields.Many2one("res.partner", ondelete="set null", index=True)
    lead_id = fields.Many2one("crm.lead", ondelete="set null", index=True)
    author_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user, readonly=True)
    body = fields.Text(default="")
    note_type = fields.Selection(
        [("agent", "Agent"), ("supervisor", "Supervisor"), ("wrap_up", "Wrap-up")],
        default="agent",
        required=True,
        index=True,
    )
    visibility = fields.Selection(
        [("agent", "Agent and supervisors"), ("supervisor", "Supervisors only")],
        default="agent",
        required=True,
    )
    client_revision = fields.Char(required=True, index=True)
    revision = fields.Integer(default=1, required=True, readonly=True)
    history_ids = fields.One2many("codestra.call.note.revision", "note_id")

    _note_client_revision_unique = models.Constraint(
        "UNIQUE(call_id, author_id, client_revision)", "This note revision was already saved."
    )

    @api.model_create_multi
    def create(self, values_list):
        records = super().create(values_list)
        for record in records:
            record._snapshot("created")
        return records

    def write(self, values):
        if "author_id" in values or "call_id" in values or "tenant_id" in values:
            raise AccessError("Note ownership is immutable.")
        if "body" not in values:
            return super().write(values)
        result = True
        for record in self:
            item = dict(values, revision=record.revision + 1)
            result = super(CallNote, record).write(item) and result
            record._snapshot("edited")
        return result

    def unlink(self):
        raise AccessError("Call notes are retained as audit evidence.")

    def _snapshot(self, action):
        self.env["codestra.call.note.revision"].sudo().create(
            {
                "note_id": self.id,
                "revision": self.revision,
                "body": self.body,
                "editor_id": self.env.user.id,
                "action": action,
            }
        )


class CallNoteRevision(models.Model):
    _name = "codestra.call.note.revision"
    _description = "Immutable call note revision"
    _order = "create_date desc, id desc"

    note_id = fields.Many2one("codestra.call.note", required=True, ondelete="restrict", index=True)
    revision = fields.Integer(required=True)
    body = fields.Text(required=True)
    editor_id = fields.Many2one("res.users", required=True, readonly=True)
    action = fields.Selection([("created", "Created"), ("edited", "Edited")], required=True)

    def write(self, values):
        raise AccessError("Note history is immutable.")

    def unlink(self):
        raise AccessError("Note history is immutable.")


class CallSubDisposition(models.Model):
    _name = "codestra.call.sub.disposition"
    _description = "Campaign call sub-disposition"
    _order = "sequence, name"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    parent_id = fields.Many2one("codestra.vicidial.disposition", required=True, ondelete="cascade", index=True)
    campaign_ids = fields.Many2many("codestra.vicidial.campaign")
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    requires_callback = fields.Boolean()
    requires_task = fields.Boolean()

    _sub_disposition_unique = models.Constraint(
        "UNIQUE(parent_id, code)", "Sub-disposition codes must be unique per disposition."
    )


class CallNoteTemplate(models.Model):
    _name = "codestra.call.note.template"
    _description = "Campaign note template"
    _order = "sequence, name"

    name = fields.Char(required=True)
    body = fields.Text(required=True)
    campaign_ids = fields.Many2many("codestra.vicidial.campaign", required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)


class CallQAReview(models.Model):
    _name = "codestra.call.qa.review"
    _description = "Call quality review"
    _order = "reviewed_at desc, id desc"

    call_id = fields.Many2one("codestra.vicidial.call", required=True, ondelete="restrict", index=True)
    tenant_id = fields.Char(related="call_id.tenant_id", store=True, index=True)
    reviewer_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user, readonly=True)
    reviewed_at = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)
    greeting = fields.Integer(required=True)
    verification = fields.Integer(required=True)
    product_knowledge = fields.Integer(required=True)
    compliance = fields.Integer(required=True)
    call_control = fields.Integer(required=True)
    empathy = fields.Integer(required=True)
    closing = fields.Integer(required=True)
    score = fields.Float(compute="_compute_score", store=True)
    comment = fields.Text()
    coaching_required = fields.Boolean()
    state = fields.Selection([("draft", "Draft"), ("submitted", "Submitted")], default="draft", required=True)

    @api.depends("greeting", "verification", "product_knowledge", "compliance", "call_control", "empathy", "closing")
    def _compute_score(self):
        for record in self:
            values = [
                record.greeting,
                record.verification,
                record.product_knowledge,
                record.compliance,
                record.call_control,
                record.empathy,
                record.closing,
            ]
            record.score = sum(values) / len(values) * 20

    @api.constrains("greeting", "verification", "product_knowledge", "compliance", "call_control", "empathy", "closing")
    def _score_range(self):
        for record in self:
            values = [
                record.greeting,
                record.verification,
                record.product_knowledge,
                record.compliance,
                record.call_control,
                record.empathy,
                record.closing,
            ]
            if any(value < 0 or value > 5 for value in values):
                raise ValidationError("QA category scores must be between zero and five.")

    def unlink(self):
        raise AccessError("Submitted quality evidence cannot be deleted.")

    def write(self, values):
        if any(record.state == "submitted" for record in self):
            raise AccessError("Submitted quality evidence is immutable.")
        return super().write(values)


class CallCoaching(models.Model):
    _name = "codestra.call.coaching"
    _description = "Call coaching task"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True, tracking=True)
    review_id = fields.Many2one("codestra.call.qa.review", required=True, ondelete="restrict", index=True)
    call_id = fields.Many2one(related="review_id.call_id", store=True, index=True)
    tenant_id = fields.Char(related="review_id.tenant_id", store=True, index=True)
    assigned_agent_id = fields.Many2one("res.users", required=True, tracking=True)
    due_date = fields.Date(required=True, tracking=True)
    comments = fields.Text(tracking=True)
    state = fields.Selection(
        [("open", "Open"), ("acknowledged", "Acknowledged"), ("completed", "Completed")],
        default="open",
        required=True,
        tracking=True,
    )
    acknowledged_at = fields.Datetime(readonly=True)

    def write(self, values):
        reviewer = self.env.user.has_group("codestra_vicidial_crm.group_supervisor") or self.env.user.has_group(
            "codestra_vicidial_crm.group_qa"
        )
        if not reviewer and not (
            self.env.context.get("codestra_acknowledge")
            and set(values) == {"state", "acknowledged_at"}
            and values.get("state") == "acknowledged"
        ):
            raise AccessError("Agents may only acknowledge their own coaching task.")
        return super().write(values)

    def action_acknowledge(self):
        for record in self:
            if record.assigned_agent_id != self.env.user:
                raise AccessError("Only the assigned agent may acknowledge coaching.")
            if record.state != "open":
                raise ValidationError("Only open coaching can be acknowledged.")
            record.with_context(codestra_acknowledge=True).write(
                {
                    "state": "acknowledged",
                    "acknowledged_at": fields.Datetime.now(),
                }
            )
        return True

    def unlink(self):
        raise AccessError("Coaching evidence cannot be deleted.")
