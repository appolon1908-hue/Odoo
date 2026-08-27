from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class CodestraClientContract(models.Model):
    _name = "codestra.client.contract"
    _description = "Codestra Client Contract"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "name, version desc"
    _check_company_auto = True

    _VERSIONED_FIELDS = {
        "client_id",
        "authorized_contact_ids",
        "campaign_ids",
        "currency_id",
        "billing_model",
        "start_date",
        "end_date",
        "service_scope",
    }

    name = fields.Char(
        string="Contract Number",
        required=True,
        readonly=True,
        copy=False,
        index=True,
        default=lambda self: _("New"),
    )
    version = fields.Integer(required=True, default=1, readonly=True, tracking=True)
    predecessor_id = fields.Many2one(
        "codestra.client.contract",
        readonly=True,
        copy=False,
        ondelete="restrict",
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    client_id = fields.Many2one(
        "res.partner",
        required=True,
        ondelete="restrict",
        domain="[('is_company', '=', True)]",
        index=True,
        tracking=True,
    )
    authorized_contact_ids = fields.Many2many(
        "res.partner",
        "codestra_client_contract_contact_rel",
        "contract_id",
        "partner_id",
        string="Authorized Contacts",
        tracking=True,
    )
    campaign_ids = fields.Many2many(
        "call.center.campaign",
        "codestra_client_contract_campaign_rel",
        "contract_id",
        "campaign_id",
        string="Governed Campaigns",
        tracking=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
        tracking=True,
    )
    billing_model = fields.Selection(
        [
            ("fixed", "Fixed Fee"),
            ("hourly", "Per Agent Hour"),
            ("interaction", "Per Interaction"),
            ("lead", "Per Qualified Lead"),
            ("appointment", "Per Appointment"),
            ("sale", "Per Sale"),
            ("hybrid", "Hybrid"),
        ],
        required=True,
        default="fixed",
        tracking=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("in_review", "In Review"),
            ("approved", "Approved"),
            ("active", "Active"),
            ("suspended", "Suspended"),
            ("expired", "Expired"),
            ("terminated", "Terminated"),
        ],
        required=True,
        default="draft",
        index=True,
        tracking=True,
        copy=False,
    )
    start_date = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    end_date = fields.Date(tracking=True)
    service_scope = fields.Text(required=True)
    approval_user_id = fields.Many2one("res.users", readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    activated_at = fields.Datetime(readonly=True, copy=False)
    sla_ids = fields.One2many("codestra.client.sla", "contract_id", copy=True)

    _contract_version_unique = models.Constraint(
        "unique(company_id, name, version)",
        "Contract number and version must be unique within a company.",
    )

    @api.model_create_multi
    def create(self, values_list):
        sequence = self.env["ir.sequence"]
        for values in values_list:
            if values.get("name", _("New")) == _("New"):
                values["name"] = sequence.next_by_code("codestra.client.contract") or _("New")
        return super().create(values_list)

    @api.constrains("start_date", "end_date")
    def _check_effective_dates(self):
        for record in self:
            if record.start_date and record.end_date and record.end_date < record.start_date:
                raise ValidationError(_("Contract end date cannot precede its start date."))

    @api.constrains("authorized_contact_ids", "client_id")
    def _check_authorized_contacts(self):
        for record in self:
            invalid = record.authorized_contact_ids.filtered(
                lambda contact: contact != record.client_id and contact.parent_id != record.client_id
            )
            if invalid:
                raise ValidationError(_("Authorized contacts must belong to the client company."))

    def write(self, values):
        if not self.env.context.get("contract_version_write") and self._VERSIONED_FIELDS.intersection(values):
            frozen = self.filtered(lambda record: record.state in {"approved", "active", "suspended"})
            if frozen:
                raise UserError(_("Approved contract terms are immutable; create a new version."))
        return super().write(values)

    def action_submit(self):
        for record in self:
            if record.state != "draft":
                raise UserError(_("Only draft contracts can be submitted."))
            record.state = "in_review"
        return True

    def action_approve(self):
        for record in self:
            if record.state != "in_review":
                raise UserError(_("Only contracts in review can be approved."))
            if not record.authorized_contact_ids:
                raise ValidationError(_("At least one authorized client contact is required."))
            if not record.sla_ids.filtered("active"):
                raise ValidationError(_("At least one active SLA definition is required."))
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
                raise UserError(_("Only approved contracts can be activated."))
            if not record.campaign_ids:
                raise ValidationError(_("At least one governed campaign is required before activation."))
            record.write({"state": "active", "activated_at": fields.Datetime.now()})
        return True

    def action_suspend(self):
        for record in self:
            if record.state != "active":
                raise UserError(_("Only active contracts can be suspended."))
            record.state = "suspended"
        return True

    def action_resume(self):
        for record in self:
            if record.state != "suspended":
                raise UserError(_("Only suspended contracts can be resumed."))
            record.state = "active"
        return True

    def action_terminate(self):
        for record in self:
            if record.state not in {"approved", "active", "suspended"}:
                raise UserError(_("This contract cannot be terminated from its current state."))
            record.state = "terminated"
        return True

    def action_create_version(self):
        self.ensure_one()
        if self.state not in {"approved", "active", "suspended"}:
            raise UserError(_("Create a new version only from an approved contract."))
        return self.with_context(contract_version_write=True).copy(
            {
                "name": self.name,
                "version": self.version + 1,
                "predecessor_id": self.id,
                "state": "draft",
                "approval_user_id": False,
                "approved_at": False,
                "activated_at": False,
            }
        )


class CodestraClientSla(models.Model):
    _name = "codestra.client.sla"
    _description = "Codestra Client SLA"
    _order = "contract_id, metric_code"
    _check_company_auto = True

    contract_id = fields.Many2one(
        "codestra.client.contract",
        required=True,
        ondelete="cascade",
        check_company=True,
        index=True,
    )
    company_id = fields.Many2one(
        related="contract_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )
    metric_code = fields.Char(required=True, index=True)
    name = fields.Char(required=True)
    operator = fields.Selection(
        [("lte", "At Most"), ("gte", "At Least")],
        required=True,
        default="lte",
    )
    target_value = fields.Float(required=True)
    warning_value = fields.Float()
    unit = fields.Selection(
        [
            ("seconds", "Seconds"),
            ("minutes", "Minutes"),
            ("hours", "Hours"),
            ("percent", "Percent"),
            ("count", "Count"),
        ],
        required=True,
        default="percent",
    )
    active = fields.Boolean(default=True)

    _contract_metric_unique = models.Constraint(
        "unique(contract_id, metric_code)",
        "An SLA metric may be defined once per contract version.",
    )

    @api.constrains("target_value", "warning_value")
    def _check_values(self):
        for record in self:
            if record.target_value < 0 or record.warning_value < 0:
                raise ValidationError(_("SLA values cannot be negative."))
            if record.unit == "percent" and (
                record.target_value > 100 or record.warning_value > 100
            ):
                raise ValidationError(_("Percentage SLA values cannot exceed 100."))
