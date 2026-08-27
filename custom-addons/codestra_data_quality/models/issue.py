import uuid

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class CodestraDataQualityIssue(models.Model):
    _name = "codestra.data.quality.issue"
    _description = "Codestra Data Quality Issue"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "severity desc, create_date desc"
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
    idempotency_key = fields.Char(
        required=True,
        copy=False,
        default=lambda self: str(uuid.uuid4()),
        index=True,
    )
    res_model = fields.Selection(
        [
            ("res.partner", "Contact"),
            ("crm.lead", "Lead / Opportunity"),
            ("codestra.client.contract", "Client Contract"),
            ("codestra.vicidial.call", "Call"),
        ],
        required=True,
        index=True,
    )
    res_id = fields.Integer(required=True, index=True)
    duplicate_res_id = fields.Integer(index=True)
    issue_type = fields.Selection(
        [
            ("invalid_phone", "Invalid Phone"),
            ("invalid_email", "Invalid Email"),
            ("incomplete", "Incomplete Record"),
            ("duplicate", "Duplicate Candidate"),
            ("identity_conflict", "Identity Conflict"),
            ("cross_reference", "Cross-reference Mismatch"),
        ],
        required=True,
        index=True,
        tracking=True,
    )
    severity = fields.Selection(
        [("0", "Low"), ("1", "Normal"), ("2", "High"), ("3", "Critical")],
        required=True,
        default="1",
        index=True,
        tracking=True,
    )
    normalized_value = fields.Char(index=True)
    state = fields.Selection(
        [
            ("open", "Open"),
            ("in_review", "In Review"),
            ("resolved", "Resolved"),
            ("ignored", "Ignored"),
        ],
        required=True,
        default="open",
        index=True,
        tracking=True,
        copy=False,
    )
    assignee_id = fields.Many2one("res.users", tracking=True)
    resolution = fields.Text(tracking=True)

    _idempotency_unique = models.Constraint(
        "unique(idempotency_key)",
        "A data-quality issue idempotency key may be recorded once.",
    )

    @api.model_create_multi
    def create(self, values_list):
        sequence = self.env["ir.sequence"]
        for values in values_list:
            if values.get("name", _("New")) == _("New"):
                values["name"] = sequence.next_by_code("codestra.data.quality.issue") or _("New")
        return super().create(values_list)

    @api.constrains("res_id", "duplicate_res_id", "issue_type")
    def _check_record_references(self):
        for record in self:
            if record.res_id <= 0 or record.duplicate_res_id < 0:
                raise ValidationError(_("Data-quality record references must be positive identifiers."))
            if record.issue_type == "duplicate" and not record.duplicate_res_id:
                raise ValidationError(_("Duplicate issues require a duplicate candidate reference."))
            if record.duplicate_res_id and record.duplicate_res_id == record.res_id:
                raise ValidationError(_("A record cannot be its own duplicate candidate."))

    def action_start_review(self):
        for record in self:
            if record.state != "open":
                raise UserError(_("Only open issues can enter review."))
            record.write({"state": "in_review", "assignee_id": self.env.user.id})
        return True

    def action_resolve(self):
        for record in self:
            if record.state not in {"open", "in_review"}:
                raise UserError(_("Only open or in-review issues can be resolved."))
            if not (record.resolution or "").strip():
                raise ValidationError(_("A reviewed resolution is required."))
            record.state = "resolved"
        return True

    def action_ignore(self):
        for record in self:
            if record.state not in {"open", "in_review"}:
                raise UserError(_("Only open or in-review issues can be ignored."))
            if not (record.resolution or "").strip():
                raise ValidationError(_("An ignore rationale is required."))
            record.state = "ignored"
        return True

    def action_reopen(self):
        for record in self:
            if record.state not in {"resolved", "ignored"}:
                raise UserError(_("Only resolved or ignored issues can be reopened."))
            record.state = "open"
        return True
