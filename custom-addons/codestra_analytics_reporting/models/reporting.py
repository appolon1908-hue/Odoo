from odoo import api, fields, models
from odoo.exceptions import ValidationError


class ReportingScope(models.AbstractModel):
    _name = "codestra.reporting.scope.mixin"
    _description = "Reporting Scope"

    environment = fields.Selection(
        [("test", "Test"), ("staging", "Staging"), ("production", "Production")],
        required=True, default="staging", index=True,
    )
    business_unit_id = fields.Many2one("call.center.business.unit", required=True, index=True)
    campaign_id = fields.Many2one("call.center.campaign", index=True)
    department_id = fields.Many2one("call.center.department", index=True)
    team_id = fields.Many2one("call.center.team", index=True)
    supervisor_id = fields.Many2one("res.users", index=True)
    agent_id = fields.Many2one("res.users", index=True)
    role_code = fields.Char(index=True)
    period_reference = fields.Char(required=True, index=True)
    data_cutoff_at = fields.Datetime(required=True)
    reconciliation_state = fields.Selection([
        ("pending", "Pending"), ("passed", "Passed"), ("partial", "Partial"),
        ("blocked", "Blocked"),
    ], default="pending", required=True)
    source_version = fields.Char(required=True)
    metric_definition_version = fields.Char(required=True)
    generated_at = fields.Datetime(required=True, default=fields.Datetime.now)
    security_classification = fields.Selection([
        ("internal", "Internal"), ("restricted", "Restricted"),
        ("confidential", "Confidential"),
    ], default="restricted", required=True)
    test_only = fields.Boolean(default=True, required=True)
    active = fields.Boolean(default=False)

    @api.constrains("business_unit_id", "campaign_id", "department_id", "team_id")
    def _validate_scope(self):
        for row in self:
            scoped = [x for x in (row.campaign_id, row.department_id, row.team_id) if x]
            if any(x.business_unit_id != row.business_unit_id for x in scoped):
                raise ValidationError("Reporting records cannot cross business units.")


class MetricDefinition(models.Model):
    _name = "codestra.reporting.metric.definition"
    _description = "Metric Definition"
    _inherit = ["codestra.reporting.scope.mixin"]

    technical_code = fields.Char(required=True, index=True)
    display_name = fields.Char(required=True)
    category = fields.Char(required=True)
    description = fields.Text(required=True)
    formula = fields.Text(required=True)
    numerator = fields.Char()
    denominator = fields.Char()
    exclusions = fields.Text()
    authoritative_source = fields.Char(required=True)
    unit = fields.Char(required=True)
    direction = fields.Selection([
        ("higher_is_better", "Higher Is Better"),
        ("lower_is_better", "Lower Is Better"),
        ("target_range", "Target Range"),
        ("informational", "Informational"),
    ], required=True)
    aggregation = fields.Char(required=True)
    timezone_policy = fields.Char(required=True)
    default_target = fields.Float()
    warning_threshold = fields.Float()
    critical_threshold = fields.Float()
    version = fields.Integer(required=True, default=1)
    effective_date = fields.Date(required=True)
    _code_version_unique = models.Constraint(
        "unique(technical_code, version, business_unit_id, campaign_id)",
        "Metric versions must be unique per reporting scope.",
    )


def _scoped_model(model_name, description, with_score=False):
    values = {
        "__module__": __name__,
        "_name": model_name,
        "_description": description,
        "_inherit": ["codestra.reporting.scope.mixin"],
        "reference": fields.Char(required=True, index=True),
        "safe_payload": fields.Json(),
    }
    if with_score:
        values.update({
            "score": fields.Float(),
            "score_level": fields.Char(),
            "sample_size": fields.Integer(default=0),
            "minimum_sample_met": fields.Boolean(default=False),
            "advisory_only": fields.Boolean(default=True, required=True),
            "component_breakdown": fields.Json(),
        })
    return type(model_name.replace(".", "_"), (models.Model,), values)


MetricTarget = _scoped_model("codestra.reporting.metric.target", "Metric Target")
Period = _scoped_model("codestra.reporting.period", "Reporting Period")
Snapshot = _scoped_model("codestra.reporting.snapshot", "Reporting Snapshot")
AgentScore = _scoped_model("codestra.reporting.agent.score", "Agent Score", True)
SupervisorScore = _scoped_model("codestra.reporting.supervisor.score", "Supervisor Score", True)
DepartmentScore = _scoped_model("codestra.reporting.department.score", "Department Score", True)
CampaignScore = _scoped_model("codestra.reporting.campaign.score", "Campaign Score", True)
BusinessUnitScore = _scoped_model("codestra.reporting.business.unit.score", "Business Unit Score", True)
CallScore = _scoped_model("codestra.reporting.call.score", "Call Score", True)
LeadScore = _scoped_model("codestra.reporting.lead.score", "Lead Score", True)
StaffingInterval = _scoped_model("codestra.reporting.staffing.interval", "Staffing Interval")
PerformanceAlert = _scoped_model("codestra.reporting.performance.alert", "Performance Alert")
ReconciliationRun = _scoped_model("codestra.reporting.reconciliation.run", "Reconciliation Run")
ReconciliationFinding = _scoped_model("codestra.reporting.reconciliation.finding", "Reconciliation Finding")
ReportingExport = _scoped_model("codestra.reporting.export", "Controlled Reporting Export")
ReportingDelivery = _scoped_model("codestra.reporting.delivery", "Reporting Delivery")
Forecast = _scoped_model("codestra.reporting.forecast", "Reporting Forecast")
