from datetime import date

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class CodestraRatePlan(models.Model):
    _name = "codestra.rate.plan"
    _description = "Codestra Rate Plan"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "contract_id, billable_unit, effective_from desc"
    _check_company_auto = True

    name = fields.Char(required=True, tracking=True)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    contract_id = fields.Many2one(
        "codestra.client.contract",
        required=True,
        ondelete="restrict",
        check_company=True,
        index=True,
        tracking=True,
    )
    campaign_id = fields.Many2one(
        "call.center.campaign",
        string="Governed Campaign",
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    billable_unit = fields.Selection(
        [
            ("agent_hour", "Agent Hour"),
            ("interaction", "Interaction"),
            ("qualified_lead", "Qualified Lead"),
            ("appointment", "Appointment"),
            ("sale", "Sale"),
            ("email", "Email"),
            ("sms", "SMS"),
        ],
        required=True,
        index=True,
        tracking=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    client_unit_rate = fields.Monetary(required=True, currency_field="currency_id", tracking=True)
    provider_unit_cost = fields.Monetary(required=True, currency_field="currency_id", tracking=True)
    effective_from = fields.Date(required=True, default=fields.Date.context_today, index=True)
    effective_to = fields.Date(index=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("approved", "Approved"),
            ("active", "Active"),
            ("retired", "Retired"),
        ],
        required=True,
        default="draft",
        index=True,
        tracking=True,
        copy=False,
    )
    approval_user_id = fields.Many2one("res.users", readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)

    @api.constrains("client_unit_rate", "provider_unit_cost")
    def _check_rates(self):
        for record in self:
            if record.client_unit_rate < 0 or record.provider_unit_cost < 0:
                raise ValidationError(_("Rates and provider costs cannot be negative."))

    @api.constrains("effective_from", "effective_to")
    def _check_dates(self):
        for record in self:
            if record.effective_to and record.effective_to < record.effective_from:
                raise ValidationError(_("Rate-plan end date cannot precede its start date."))

    @api.constrains(
        "state",
        "company_id",
        "contract_id",
        "campaign_id",
        "billable_unit",
        "effective_from",
        "effective_to",
    )
    def _check_effective_overlap(self):
        for record in self.filtered(lambda item: item.state in {"approved", "active"}):
            range_end = record.effective_to or date.max
            domain = [
                ("id", "!=", record.id),
                ("company_id", "=", record.company_id.id),
                ("contract_id", "=", record.contract_id.id),
                ("campaign_id", "=", record.campaign_id.id or False),
                ("billable_unit", "=", record.billable_unit),
                ("state", "in", ["approved", "active"]),
                ("effective_from", "<=", range_end),
                "|",
                ("effective_to", "=", False),
                ("effective_to", ">=", record.effective_from),
            ]
            if self.search_count(domain):
                raise ValidationError(_("Approved rate-plan effective ranges cannot overlap."))

    def write(self, values):
        protected = {
            "contract_id",
            "campaign_id",
            "billable_unit",
            "currency_id",
            "client_unit_rate",
            "provider_unit_cost",
            "effective_from",
            "effective_to",
        }
        if protected.intersection(values) and self.filtered(lambda item: item.state in {"approved", "active"}):
            raise UserError(_("Approved rate plans are immutable; create a new plan version."))
        return super().write(values)

    def action_approve(self):
        for record in self:
            if record.state != "draft":
                raise UserError(_("Only draft rate plans can be approved."))
            if record.contract_id.state not in {"approved", "active"}:
                raise ValidationError(_("The client contract must be approved before its rate plan."))
            record.write(
                {
                    "state": "approved",
                    "approval_user_id": self.env.user.id,
                    "approved_at": fields.Datetime.now(),
                }
            )
        return True

    def action_activate(self):
        for record in self:
            if record.state != "approved":
                raise UserError(_("Only approved rate plans can be activated."))
            record.state = "active"
        return True

    def action_retire(self):
        for record in self:
            if record.state not in {"approved", "active"}:
                raise UserError(_("Only approved or active rate plans can be retired."))
            record.state = "retired"
        return True


class CodestraBillingUsage(models.Model):
    _name = "codestra.billing.usage"
    _description = "Codestra Billable Usage"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "occurred_at desc, id desc"
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
    contract_id = fields.Many2one(
        "codestra.client.contract",
        required=True,
        ondelete="restrict",
        check_company=True,
        index=True,
    )
    rate_plan_id = fields.Many2one(
        "codestra.rate.plan",
        required=True,
        ondelete="restrict",
        check_company=True,
        index=True,
    )
    currency_id = fields.Many2one(
        related="rate_plan_id.currency_id",
        store=True,
        readonly=True,
    )
    source_system = fields.Char(required=True, index=True)
    source_reference = fields.Char(required=True, index=True)
    idempotency_key = fields.Char(required=True, copy=False, index=True)
    occurred_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    units = fields.Float(required=True)
    rate_snapshot = fields.Monetary(required=True, currency_field="currency_id", copy=False)
    provider_cost_snapshot = fields.Monetary(required=True, currency_field="currency_id", copy=False)
    revenue = fields.Monetary(compute="_compute_amounts", store=True, currency_field="currency_id")
    provider_cost = fields.Monetary(compute="_compute_amounts", store=True, currency_field="currency_id")
    margin = fields.Monetary(compute="_compute_amounts", store=True, currency_field="currency_id")
    state = fields.Selection(
        [
            ("pending", "Pending Review"),
            ("approved", "Approved"),
            ("invoiced", "Invoiced"),
            ("reversed", "Reversed"),
        ],
        required=True,
        default="pending",
        index=True,
        tracking=True,
        copy=False,
    )
    invoice_id = fields.Many2one("account.move", ondelete="restrict", tracking=True)

    _usage_idempotency_unique = models.Constraint(
        "unique(idempotency_key)",
        "A billable usage idempotency key may be recorded once.",
    )
    _usage_source_unique = models.Constraint(
        "unique(source_system, source_reference)",
        "A source usage reference may be billed once.",
    )

    @api.model_create_multi
    def create(self, values_list):
        sequence = self.env["ir.sequence"]
        for values in values_list:
            plan = self.env["codestra.rate.plan"].browse(values.get("rate_plan_id")).exists()
            if not plan or plan.state != "active":
                raise ValidationError(_("Billable usage requires an active rate plan."))
            if values.get("contract_id") and values["contract_id"] != plan.contract_id.id:
                raise ValidationError(_("Usage contract and rate plan must match."))
            values.setdefault("contract_id", plan.contract_id.id)
            values.setdefault("company_id", plan.company_id.id)
            values.setdefault("rate_snapshot", plan.client_unit_rate)
            values.setdefault("provider_cost_snapshot", plan.provider_unit_cost)
            if values.get("name", _("New")) == _("New"):
                values["name"] = sequence.next_by_code("codestra.billing.usage") or _("New")
        return super().create(values_list)

    @api.depends("units", "rate_snapshot", "provider_cost_snapshot")
    def _compute_amounts(self):
        for record in self:
            record.revenue = record.units * record.rate_snapshot
            record.provider_cost = record.units * record.provider_cost_snapshot
            record.margin = record.revenue - record.provider_cost

    @api.constrains("units")
    def _check_units(self):
        for record in self:
            if record.units <= 0:
                raise ValidationError(_("Billable usage units must be greater than zero."))

    def write(self, values):
        protected = {
            "contract_id",
            "rate_plan_id",
            "source_system",
            "source_reference",
            "idempotency_key",
            "occurred_at",
            "units",
            "rate_snapshot",
            "provider_cost_snapshot",
        }
        if protected.intersection(values) and self.filtered(lambda item: item.state in {"approved", "invoiced"}):
            raise UserError(_("Approved or invoiced usage is immutable; reverse it with evidence."))
        return super().write(values)

    def action_approve(self):
        for record in self:
            if record.state != "pending":
                raise UserError(_("Only pending usage can be approved."))
            record.state = "approved"
        return True

    def action_mark_invoiced(self):
        for record in self:
            if record.state != "approved" or not record.invoice_id:
                raise ValidationError(_("Approved usage requires an invoice before it can be marked invoiced."))
            record.state = "invoiced"
        return True

    def action_reverse(self):
        for record in self:
            if record.state not in {"pending", "approved"}:
                raise UserError(_("Only pending or approved usage can be reversed here."))
            record.state = "reversed"
        return True
