from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CallCenterTeam(models.Model):
    _name = "call.center.team"
    _description = "Call Center Team"
    _inherit = ["mail.thread", "call.center.business.unit.mixin"]

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(index=True)
    active = fields.Boolean(default=True)
    department_id = fields.Many2one(
        "call.center.department", required=True, ondelete="restrict", index=True
    )
    manager_id = fields.Many2one("res.users", tracking=True)
    agent_ids = fields.Many2many(
        "res.users", "call_center_team_agent_rel", string="Agents"
    )
    supervisor_ids = fields.Many2many(
        "res.users", "call_center_team_supervisor_rel", string="Supervisors"
    )
    language_codes = fields.Char(help="Comma-separated ISO language codes.")
    skill_tags = fields.Char()
    capacity = fields.Integer(default=1)
    canary_only = fields.Boolean(default=False, required=True, index=True)
    customer_traffic_allowed = fields.Boolean(default=True, required=True, index=True)

    @api.constrains("capacity")
    def _check_capacity(self):
        if any(team.capacity < 1 for team in self):
            raise ValidationError("Team capacity must be at least one.")

    @api.constrains("canary_only", "customer_traffic_allowed")
    def _check_canary_safety(self):
        if any(team.canary_only and team.customer_traffic_allowed for team in self):
            raise ValidationError("Canary-only teams cannot receive customer traffic.")

    _code_unit_unique = models.Constraint(
        "unique(code, business_unit_id)",
        "Operational-team codes must be unique within a business unit.",
    )

    @api.constrains(
        "business_unit_id", "department_id", "manager_id", "agent_ids", "supervisor_ids"
    )
    def _check_operational_scope(self):
        for team in self:
            if (
                team.department_id
                and team.department_id.business_unit_id != team.business_unit_id
            ):
                raise ValidationError(
                    "An operational team and its department must share a business unit."
                )
            for user in team.manager_id | team.agent_ids | team.supervisor_ids:
                if (
                    user.call_center_business_unit_ids
                    and team.business_unit_id not in user.call_center_business_unit_ids
                ):
                    raise ValidationError(
                        "Operational-team users must be authorized for its business unit."
                    )


class CallCenterCampaign(models.Model):
    _name = "call.center.campaign"
    _description = "Call Center Campaign"
    _inherit = [
        "mail.thread",
        "mail.activity.mixin",
        "call.center.business.unit.mixin",
    ]
    _order = "start_date desc, name"

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, index=True, tracking=True)
    active = fields.Boolean(default=True)
    is_template = fields.Boolean(default=False, tracking=True)
    campaign_type = fields.Selection(
        [("sales", "Sales"), ("service", "Service"), ("retention", "Retention"),
         ("winback", "Win-Back"), ("research", "Research")],
        required=True,
        default="sales",
        tracking=True,
    )
    direction = fields.Selection(
        [("inbound", "Inbound"), ("outbound", "Outbound"), ("blended", "Blended")],
        required=True,
        default="outbound",
        tracking=True,
    )
    state = fields.Selection(
        [("draft", "Draft"), ("approved", "Approved"), ("active", "Active"),
         ("paused", "Paused"), ("closed", "Closed")],
        default="draft",
        required=True,
        tracking=True,
    )
    start_date = fields.Date()
    end_date = fields.Date()
    timezone = fields.Selection(
        selection=lambda self: self.env["res.users"]._fields["tz"]._description_selection(self.env),
        default=lambda self: self.env.user.tz or "UTC",
        required=True,
    )
    calling_hour_start = fields.Float(default=9.0)
    calling_hour_end = fields.Float(default=17.0)
    lead_source_id = fields.Many2one("utm.source")
    target_audience = fields.Text()
    team_ids = fields.Many2many("call.center.team", string="Teams")
    agent_ids = fields.Many2many(
        "res.users", "call_center_campaign_agent_rel", string="Assigned Agents"
    )
    supervisor_ids = fields.Many2many(
        "res.users", "call_center_campaign_supervisor_rel", string="Supervisors"
    )
    dialer_mode = fields.Selection(
        [("click", "Click-to-call"), ("preview", "Preview"),
         ("progressive", "Progressive"), ("predictive", "Predictive"),
         ("power", "Power"), ("callback", "Scheduled Callback")],
        default="preview",
        required=True,
    )
    routing_strategy = fields.Selection(
        [("round_robin", "Round Robin"), ("weighted", "Weighted Round Robin"),
         ("skill", "Skill Based"), ("language", "Language Based"),
         ("territory", "Territory"), ("performance", "Performance"),
         ("priority", "Priority"), ("manual", "Manual")],
        default="round_robin",
        required=True,
    )
    consent_required = fields.Boolean(default=True)
    dnc_enforced = fields.Boolean(default=True)
    max_call_attempts = fields.Integer(default=3)
    max_retries = fields.Integer(default=1)
    callback_rule = fields.Text()
    escalation_rule = fields.Text()
    qualification_questions = fields.Text()
    fulfillment_workflow = fields.Text()
    retention_workflow = fields.Text()
    upsell_workflow = fields.Text()
    kpi_definition = fields.Text()
    cost_center = fields.Char()
    budget = fields.Monetary(currency_field="currency_id")
    revenue_target = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id, required=True
    )
    script_ids = fields.One2many("call.center.script", "campaign_id")
    current_script_id = fields.Many2one(
        "call.center.script", compute="_compute_current_script"
    )

    _code_unique = models.Constraint(
        "unique(code)",
        "Campaign codes must be globally unique.",
    )

    @api.constrains(
        "business_unit_id", "team_ids", "agent_ids", "supervisor_ids"
    )
    def _check_assignment_scope(self):
        for campaign in self:
            if any(
                team.business_unit_id != campaign.business_unit_id
                for team in campaign.team_ids
            ):
                raise ValidationError(
                    "Campaign operational teams must belong to its business unit."
                )
            for user in campaign.agent_ids | campaign.supervisor_ids:
                if (
                    user.call_center_business_unit_ids
                    and campaign.business_unit_id
                    not in user.call_center_business_unit_ids
                ):
                    raise ValidationError(
                        "Campaign users must be authorized for its business unit."
                    )

    @api.depends("script_ids.state", "script_ids.effective_date")
    def _compute_current_script(self):
        today = fields.Date.context_today(self)
        for campaign in self:
            campaign.current_script_id = campaign.script_ids.filtered(
                lambda script: script.state == "approved"
                and (not script.effective_date or script.effective_date <= today)
            ).sorted(lambda script: (script.effective_date or fields.Date.from_string("1900-01-01"), script.version), reverse=True)[:1]

    @api.constrains("start_date", "end_date", "calling_hour_start", "calling_hour_end")
    def _check_dates_and_hours(self):
        for campaign in self:
            if campaign.start_date and campaign.end_date and campaign.end_date < campaign.start_date:
                raise ValidationError("Campaign end date cannot precede its start date.")
            if not (0 <= campaign.calling_hour_start < campaign.calling_hour_end <= 24):
                raise ValidationError("Calling hours must be an increasing range within 0–24.")

    def action_duplicate_template(self):
        self.ensure_one()
        return self.copy(
            {"name": f"{self.name} (Copy)", "code": f"{self.code}-COPY-{self.id}",
             "is_template": False, "state": "draft"}
        )

    def write(self, vals):
        tracked = {"state", "agent_ids", "supervisor_ids", "team_ids"}
        before = {record.id: {key: record[key] for key in tracked & vals.keys()} for record in self}
        result = super().write(vals)
        for record in self:
            if tracked & vals.keys():
                self.env["call.center.audit.event"].sudo().create(
                    {
                        "business_unit_id": record.business_unit_id.id,
                        "event_type": "campaign.changed",
                        "model_name": record._name,
                        "record_id": record.id,
                        "previous_values_json": before[record.id],
                        "new_values_json": {key: vals[key] for key in tracked & vals.keys()},
                    }
                )
        return result
