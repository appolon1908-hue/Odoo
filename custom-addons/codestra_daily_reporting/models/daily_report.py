from odoo import api, fields, models
from odoo.exceptions import ValidationError


class DailyReport(models.Model):
    _name = "codestra.daily.report"
    _description = "Immutable Daily Report"
    _inherit = "call.center.business.unit.mixin"

    name = fields.Char(required=True)
    report_date = fields.Date(required=True, index=True)
    campaign_id = fields.Many2one("call.center.campaign")
    scope = fields.Selection([("campaign","Campaign"),("business_unit","Business Unit"),
                              ("platform","Platform"),("technical","Technical")], required=True)
    version = fields.Integer(default=1, required=True)
    state = fields.Selection([("draft","Draft"),("partial","Partial Data"),
                              ("blocked","Blocked"),("delivered","Delivered"),
                              ("amended","Amended"),("archived","Archived")],
                             default="draft", required=True)
    immutable_hash = fields.Char(copy=False)
    section_ids = fields.One2many("codestra.daily.report.section", "report_id")
    recipient_ids = fields.One2many("codestra.daily.report.recipient", "report_id")
    delivery_ids = fields.One2many("codestra.daily.report.delivery", "report_id")
    action_ids = fields.One2many("codestra.daily.report.action", "report_id")
    snapshot_ids = fields.One2many("codestra.daily.report.snapshot", "report_id")
    quality_ids = fields.One2many("codestra.daily.report.data.quality", "report_id")

    _report_version_unique = models.Constraint(
        "unique(report_date, scope, campaign_id, business_unit_id, version)",
        "Report versions must be unique.")

    def write(self, values):
        if any(row.state in ("delivered", "amended", "archived") for row in self):
            allowed = {"state"}
            if set(values) - allowed:
                raise ValidationError("Delivered reports are immutable; create an amendment.")
        return super().write(values)


class ReportSection(models.Model):
    _name = "codestra.daily.report.section"
    _description = "Daily Report Section"
    report_id = fields.Many2one("codestra.daily.report", required=True, ondelete="cascade")
    code = fields.Char(required=True)
    title = fields.Char(required=True)
    metric_ids = fields.One2many("codestra.daily.report.metric", "section_id")


class ReportMetric(models.Model):
    _name = "codestra.daily.report.metric"
    _description = "Daily Report Metric"
    section_id = fields.Many2one("codestra.daily.report.section", required=True, ondelete="cascade")
    code = fields.Char(required=True)
    display_name = fields.Char(required=True)
    data_source = fields.Char(required=True)
    formula = fields.Char(required=True)
    unit = fields.Char(required=True)
    value = fields.Float()
    value_na = fields.Boolean()
    target = fields.Float()
    warning_threshold = fields.Float()
    critical_threshold = fields.Float()
    owner = fields.Char(required=True)
    drilldown_reference = fields.Char()


class ReportRecipient(models.Model):
    _name = "codestra.daily.report.recipient"
    _description = "Authorized Report Recipient"
    report_id = fields.Many2one("codestra.daily.report", required=True, ondelete="cascade")
    user_id = fields.Many2one("res.users", required=True)
    role_scope = fields.Char(required=True)
    masked_email = fields.Char()
    authorized = fields.Boolean(default=False)


class ReportDelivery(models.Model):
    _name = "codestra.daily.report.delivery"
    _description = "Report Delivery Audit"
    report_id = fields.Many2one("codestra.daily.report", required=True, ondelete="restrict")
    recipient_id = fields.Many2one("codestra.daily.report.recipient", required=True)
    idempotency_hash = fields.Char(required=True, index=True)
    state = fields.Selection([("disabled","Disabled"),("pending","Pending"),
                              ("delivered","Delivered"),("failed","Failed")],
                             default="disabled", required=True)
    delivered_at = fields.Datetime()
    _delivery_unique = models.Constraint(
        "unique(idempotency_hash)", "Report delivery idempotency hashes must be unique.")


class ReportAction(models.Model):
    _name = "codestra.daily.report.action"
    _description = "Daily Report Required Action"
    report_id = fields.Many2one("codestra.daily.report", required=True, ondelete="cascade")
    severity = fields.Selection([("critical","Critical"),("high","High"),
                                 ("moderate","Moderate"),("low","Low")], required=True)
    owner = fields.Char(required=True)
    current_value = fields.Char()
    threshold = fields.Char()
    recommended_action = fields.Text(required=True)
    deadline = fields.Datetime()
    secure_link_reference = fields.Char()


class ReportSnapshot(models.Model):
    _name = "codestra.daily.report.snapshot"
    _description = "Immutable Report Snapshot"
    report_id = fields.Many2one("codestra.daily.report", required=True, ondelete="restrict")
    snapshot_hash = fields.Char(required=True)
    values = fields.Json(required=True)
    created_at = fields.Datetime(default=fields.Datetime.now, required=True)


class ReportDataQuality(models.Model):
    _name = "codestra.daily.report.data.quality"
    _description = "Report Data Quality Gate"
    report_id = fields.Many2one("codestra.daily.report", required=True, ondelete="cascade")
    source = fields.Char(required=True)
    state = fields.Selection([("pass","Pass"),("missing","Missing"),
                              ("stale","Stale"),("failed","Failed")], required=True)
    reconciliation_ok = fields.Boolean(default=False)
    safe_detail = fields.Char()
