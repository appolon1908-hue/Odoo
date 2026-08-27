from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class CodestraAgentOnboarding(models.Model):
    _name = "codestra.agent.onboarding"
    _description = "Codestra Agent Onboarding"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "target_start_date desc, id desc"
    _check_company_auto = True

    name = fields.Char(
        required=True,
        readonly=True,
        copy=False,
        default=lambda self: _("New"),
        index=True,
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        required=True,
        check_company=True,
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    manager_id = fields.Many2one(
        "res.users",
        required=True,
        default=lambda self: self.env.user,
        tracking=True,
    )
    target_start_date = fields.Date(required=True, default=fields.Date.context_today, index=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("in_review", "In Review"),
            ("approved", "Approved"),
            ("provisioning", "Provisioning"),
            ("active", "Active"),
            ("offboarding", "Offboarding"),
            ("closed", "Closed"),
            ("failed", "Failed"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="draft",
        index=True,
        tracking=True,
        copy=False,
    )
    identity_verified = fields.Boolean(tracking=True)
    employment_documents_complete = fields.Boolean(tracking=True)
    approved_checks_complete = fields.Boolean(tracking=True)
    equipment_ready = fields.Boolean(tracking=True)
    training_complete = fields.Boolean(tracking=True)
    compliance_approved = fields.Boolean(tracking=True)
    completion_percent = fields.Float(compute="_compute_completion", store=True)
    provisioning_request_id = fields.Many2one(
        "codestra.provisioning.request",
        ondelete="restrict",
        check_company=True,
        tracking=True,
    )
    failure_reason = fields.Text(tracking=True)
    notes = fields.Text()

    _employee_start_unique = models.Constraint(
        "unique(employee_id, target_start_date)",
        "An employee may have only one onboarding record for a target start date.",
    )

    @api.model_create_multi
    def create(self, values_list):
        sequence = self.env["ir.sequence"]
        for values in values_list:
            if values.get("name", _("New")) == _("New"):
                values["name"] = sequence.next_by_code("codestra.agent.onboarding") or _("New")
        return super().create(values_list)

    @api.depends(
        "identity_verified",
        "employment_documents_complete",
        "approved_checks_complete",
        "equipment_ready",
        "training_complete",
        "compliance_approved",
    )
    def _compute_completion(self):
        fields_to_check = (
            "identity_verified",
            "employment_documents_complete",
            "approved_checks_complete",
            "equipment_ready",
            "training_complete",
            "compliance_approved",
        )
        for record in self:
            completed = sum(bool(record[field_name]) for field_name in fields_to_check)
            record.completion_percent = (completed / len(fields_to_check)) * 100

    def _require_state(self, *states):
        for record in self:
            if record.state not in states:
                raise UserError(_("This action is not permitted from the current onboarding state."))

    def action_submit(self):
        self._require_state("draft")
        self.write({"state": "in_review"})
        return True

    def action_approve(self):
        self._require_state("in_review")
        for record in self:
            if record.completion_percent != 100:
                raise ValidationError(_("Every onboarding readiness gate must pass before approval."))
        self.write({"state": "approved"})
        return True

    def action_start_provisioning(self):
        self._require_state("approved")
        for record in self:
            if not record.provisioning_request_id:
                raise ValidationError(_("Link an approved provisioning request before starting provisioning."))
            if record.provisioning_request_id.state not in {
                "approved",
                "reserving",
                "provisioning",
                "partially_provisioned",
                "verification",
                "awaiting_user_activation",
            }:
                raise ValidationError(_("The linked provisioning request is not in an executable approved state."))
        self.write({"state": "provisioning"})
        return True

    def action_activate(self):
        self._require_state("provisioning")
        for record in self:
            if not record.provisioning_request_id or record.provisioning_request_id.state != "active":
                raise ValidationError(_("Activation requires an active and reconciled provisioning request."))
        self.write({"state": "active"})
        return True

    def action_begin_offboarding(self):
        self._require_state("active")
        self.write({"state": "offboarding"})
        return True

    def action_close(self):
        self._require_state("offboarding", "cancelled")
        self.write({"state": "closed"})
        return True

    def action_fail(self):
        for record in self:
            if not (record.failure_reason or "").strip():
                raise ValidationError(_("A sanitized failure reason is required."))
        self.write({"state": "failed"})
        return True

    def action_cancel(self):
        self._require_state("draft", "in_review", "approved")
        self.write({"state": "cancelled"})
        return True

    def unlink(self):
        if any(record.state not in {"draft", "cancelled"} for record in self):
            raise UserError(_("Only draft or cancelled onboarding records may be deleted."))
        return super().unlink()
