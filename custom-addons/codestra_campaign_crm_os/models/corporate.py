import uuid
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


CASE_STATES = [(value, value.replace("_", " ").title()) for value in (
    "NEW", "OPEN", "ASSIGNED", "PENDING_CUSTOMER", "PENDING_INTERNAL",
    "ESCALATED", "UNDER_REVIEW", "RESOLVED", "CLOSED", "REOPENED",
)]
COMPLAINT_STATES = [(value, value.replace("_", " ").title()) for value in (
    "RECEIVED", "ACKNOWLEDGED", "ASSIGNED", "INVESTIGATING",
    "INTERNAL_REVIEW", "CUSTOMER_RESPONSE_DUE", "RESPONSE_SENT",
    "RESOLVED", "CLOSED", "REOPENED",
)]
AGENT_STATES = [(value, value.replace("_", " ").title()) for value in (
    "OFFLINE", "LOGGED_IN", "AVAILABLE", "ON_CALL", "WRAP_UP", "BREAK",
    "LUNCH", "TRAINING", "MEETING", "COACHING", "BACK_OFFICE",
    "TECHNICAL_ISSUE",
)]


class ContactCenterCase(models.Model):
    _name = "codestra.contact.center.case"
    _description = "Corporate Contact Center Case"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "priority desc, opened_at desc"

    case_uuid = fields.Char(default=lambda self: str(uuid.uuid4()), required=True, readonly=True, copy=False, index=True)
    case_number = fields.Char(required=True, readonly=True, copy=False, index=True, default="New")
    customer_id = fields.Many2one("res.partner", required=True, ondelete="restrict", index=True)
    lead_id = fields.Many2one("crm.lead", ondelete="restrict", index=True)
    campaign_id = fields.Many2one("call.center.campaign", required=True, ondelete="restrict", index=True)
    business_unit_id = fields.Many2one(related="campaign_id.business_unit_id", store=True, index=True)
    case_type = fields.Selection([(x, x.replace("_", " ").title()) for x in (
        "SUPPORT", "COMPLAINT", "BILLING", "PAYMENTS", "KYC", "COMPLIANCE",
        "FRAUD", "SECURITY", "TECHNICAL", "TRADING_SUPPORT", "ORDER_SUPPORT", "ESCALATION",
    )], required=True, index=True)
    category = fields.Char(required=True, index=True)
    subcategory = fields.Char(index=True)
    priority = fields.Selection([(str(x), label) for x, label in ((1, "Low"), (2, "Normal"), (3, "High"), (4, "Urgent"))], default="2", required=True, index=True)
    severity = fields.Selection([(x, x.title()) for x in ("LOW", "MEDIUM", "HIGH", "CRITICAL")], default="MEDIUM", required=True, index=True)
    owner_id = fields.Many2one("res.users", required=True, ondelete="restrict", index=True)
    team_id = fields.Many2one("call.center.team", ondelete="restrict", index=True)
    supervisor_id = fields.Many2one("res.users", ondelete="restrict", index=True)
    state = fields.Selection(CASE_STATES, default="NEW", required=True, index=True, tracking=True)
    sla_due_at = fields.Datetime(required=True, index=True)
    sla_state = fields.Selection([(x, x.replace("_", " ").title()) for x in ("SLA_OK", "SLA_AT_RISK", "SLA_BREACHED")], default="SLA_OK", required=True, index=True)
    resolution = fields.Text()
    root_cause = fields.Char()
    opened_at = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True, index=True)
    resolved_at = fields.Datetime(readonly=True)
    closed_at = fields.Datetime(readonly=True)
    correlation_id = fields.Char(default=lambda self: str(uuid.uuid4()), required=True, index=True)
    legal_hold = fields.Boolean(default=False, index=True)
    retention_policy = fields.Char(default="corporate-case-default", required=True)
    _uuid_unique = models.Constraint("unique(case_uuid)", "Case UUID must be unique.")
    _number_unique = models.Constraint("unique(case_number)", "Case number must be unique.")

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get("case_number", "New") == "New":
                values["case_number"] = self.env["ir.sequence"].next_by_code("codestra.contact.center.case") or f"CASE-{uuid.uuid4().hex[:12].upper()}"
        records = super().create(vals_list)
        records._validate_scope()
        return records

    def write(self, values):
        result = super().write(values)
        self._validate_scope()
        return result

    def _validate_scope(self):
        for record in self:
            if record.lead_id and record.lead_id.call_center_campaign_id != record.campaign_id:
                raise ValidationError("Case, lead, and campaign must share an authoritative campaign.")
            if record.team_id and record.team_id.business_unit_id != record.business_unit_id:
                raise ValidationError("Case team must belong to the case business unit.")

    def action_transition(self, state, resolution=None, reason=None):
        allowed = {
            "NEW": {"OPEN", "ASSIGNED"}, "OPEN": {"ASSIGNED", "PENDING_CUSTOMER", "PENDING_INTERNAL", "ESCALATED", "RESOLVED"},
            "ASSIGNED": {"OPEN", "PENDING_CUSTOMER", "PENDING_INTERNAL", "ESCALATED", "UNDER_REVIEW", "RESOLVED"},
            "PENDING_CUSTOMER": {"OPEN", "ESCALATED", "RESOLVED"}, "PENDING_INTERNAL": {"OPEN", "ESCALATED", "UNDER_REVIEW", "RESOLVED"},
            "ESCALATED": {"UNDER_REVIEW", "RESOLVED"}, "UNDER_REVIEW": {"OPEN", "RESOLVED"},
            "RESOLVED": {"CLOSED", "REOPENED"}, "CLOSED": {"REOPENED"}, "REOPENED": {"OPEN", "ASSIGNED"},
        }
        for record in self:
            if state not in allowed.get(record.state, set()):
                raise ValidationError(f"Invalid case transition {record.state} -> {state}.")
            if state in {"RESOLVED", "CLOSED"} and not (resolution or record.resolution):
                raise ValidationError("A resolution is required before resolving or closing a case.")
            values = {"state": state}
            if resolution:
                values["resolution"] = resolution
            if state == "RESOLVED":
                values["resolved_at"] = fields.Datetime.now()
            if state == "CLOSED":
                values["closed_at"] = fields.Datetime.now()
            record.write(values)
            self.env["codestra.activity.timeline"].sudo().create({
                "event_type": "SYSTEM_EVENT", "actor_type": "HUMAN", "actor_id": str(self.env.user.id),
                "action": "case.transition", "campaign_id": record.campaign_id.id,
                "client_id": record.customer_id.id, "lead_id": record.lead_id.id,
                "visibility": "INTERNAL", "source_system": "odoo", "correlation_id": record.correlation_id,
                "safe_detail": {"case_uuid": record.case_uuid, "new_state": state, "reason": reason},
            })
        return True


class ContactCenterComplaint(models.Model):
    _name = "codestra.contact.center.complaint"
    _description = "Formal Customer Complaint"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "received_at desc"

    complaint_uuid = fields.Char(default=lambda self: str(uuid.uuid4()), required=True, readonly=True, copy=False, index=True)
    customer_id = fields.Many2one("res.partner", required=True, ondelete="restrict", index=True)
    campaign_id = fields.Many2one("call.center.campaign", required=True, ondelete="restrict", index=True)
    business_unit_id = fields.Many2one(related="campaign_id.business_unit_id", store=True, index=True)
    agent_id = fields.Many2one("codestra.agent.profile", ondelete="restrict", index=True)
    supervisor_id = fields.Many2one("res.users", ondelete="restrict", index=True)
    owner_id = fields.Many2one("res.users", required=True, ondelete="restrict", index=True)
    state = fields.Selection(COMPLAINT_STATES, default="RECEIVED", required=True, index=True, tracking=True)
    root_cause = fields.Text()
    customer_impact = fields.Text(required=True)
    financial_impact = fields.Monetary(currency_field="currency_id")
    currency_id = fields.Many2one(related="campaign_id.currency_id", store=True)
    compliance_relevance = fields.Boolean(default=False, index=True)
    corrective_action = fields.Text()
    resolution = fields.Text()
    received_at = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True, index=True)
    resolved_at = fields.Datetime(readonly=True)
    correlation_id = fields.Char(default=lambda self: str(uuid.uuid4()), required=True, index=True)
    legal_hold = fields.Boolean(default=False, index=True)
    _uuid_unique = models.Constraint("unique(complaint_uuid)", "Complaint UUID must be unique.")

    @api.constrains("campaign_id", "agent_id")
    def _campaign_scope(self):
        for record in self:
            if record.agent_id and record.campaign_id not in record.agent_id.campaign_ids:
                raise ValidationError("Complaint agent is not assigned to the complaint campaign.")


class QAScorecard(models.Model):
    _name = "codestra.qa.scorecard"
    _description = "Campaign QA Scorecard"

    name = fields.Char(required=True)
    campaign_id = fields.Many2one("call.center.campaign", required=True, ondelete="cascade", index=True)
    version = fields.Integer(default=1, required=True)
    active = fields.Boolean(default=True)
    criterion_ids = fields.One2many("codestra.qa.criterion", "scorecard_id")
    passing_score = fields.Float(default=80.0, required=True)
    _campaign_version_unique = models.Constraint("unique(campaign_id, version)", "QA scorecard version already exists for this campaign.")


class QACriterion(models.Model):
    _name = "codestra.qa.criterion"
    _description = "QA Scorecard Criterion"

    scorecard_id = fields.Many2one("codestra.qa.scorecard", required=True, ondelete="cascade", index=True)
    code = fields.Char(required=True)
    name = fields.Char(required=True)
    weight = fields.Float(required=True, default=1.0)
    critical_error = fields.Boolean(default=False)
    compliance_flag = fields.Boolean(default=False)
    _code_unique = models.Constraint("unique(scorecard_id, code)", "QA criterion code already exists.")


class QAReview(models.Model):
    _name = "codestra.qa.review"
    _description = "Contact Center QA Review"
    _order = "reviewed_at desc"

    review_uuid = fields.Char(default=lambda self: str(uuid.uuid4()), required=True, readonly=True, copy=False, index=True)
    scorecard_id = fields.Many2one("codestra.qa.scorecard", required=True, ondelete="restrict")
    campaign_id = fields.Many2one(related="scorecard_id.campaign_id", store=True, index=True)
    call_event_id = fields.Many2one("codestra.call.event", ondelete="restrict", index=True)
    agent_id = fields.Many2one("codestra.agent.profile", required=True, ondelete="restrict", index=True)
    reviewer_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user, ondelete="restrict", index=True)
    score = fields.Float(required=True)
    critical_error = fields.Boolean(default=False, index=True)
    coaching_required = fields.Boolean(default=False, index=True)
    compliance_flag = fields.Boolean(default=False, index=True)
    evidence = fields.Json(default=dict)
    reviewed_at = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True, index=True)
    correlation_id = fields.Char(default=lambda self: str(uuid.uuid4()), required=True, index=True)
    _uuid_unique = models.Constraint("unique(review_uuid)", "QA review UUID must be unique.")

    @api.constrains("score", "campaign_id", "agent_id")
    def _validate_review(self):
        for record in self:
            if not 0 <= record.score <= 100:
                raise ValidationError("QA score must be between 0 and 100.")
            if record.campaign_id not in record.agent_id.campaign_ids:
                raise ValidationError("QA review agent is outside the scorecard campaign.")


class CoachingSession(models.Model):
    _name = "codestra.coaching.session"
    _description = "Agent Coaching Session"
    _inherit = ["mail.thread"]

    session_uuid = fields.Char(default=lambda self: str(uuid.uuid4()), required=True, readonly=True, copy=False, index=True)
    qa_review_id = fields.Many2one("codestra.qa.review", ondelete="restrict", index=True)
    campaign_id = fields.Many2one("call.center.campaign", required=True, ondelete="restrict", index=True)
    agent_id = fields.Many2one("codestra.agent.profile", required=True, ondelete="restrict", index=True)
    coach_id = fields.Many2one("res.users", required=True, ondelete="restrict", index=True)
    reason = fields.Text(required=True)
    training = fields.Text()
    action_plan = fields.Text(required=True)
    due_at = fields.Datetime(required=True, index=True)
    state = fields.Selection([(x, x.title()) for x in ("PLANNED", "DELIVERED", "ACKNOWLEDGED", "FOLLOW_UP_DUE", "COMPLETED")], default="PLANNED", required=True, index=True)
    acknowledged_at = fields.Datetime(readonly=True)
    follow_up_result = fields.Text()
    correlation_id = fields.Char(default=lambda self: str(uuid.uuid4()), required=True, index=True)
    _uuid_unique = models.Constraint("unique(session_uuid)", "Coaching session UUID must be unique.")

    def action_acknowledge(self):
        for record in self:
            if self.env.user != record.agent_id.user_id:
                raise AccessError("Only the coached employee may acknowledge this session.")
            record.write({"state": "ACKNOWLEDGED", "acknowledged_at": fields.Datetime.now()})
        return True


class AgentStateEvent(models.Model):
    _name = "codestra.agent.state.event"
    _description = "Immutable Agent State Interval"
    _order = "started_at desc"

    event_uuid = fields.Char(default=lambda self: str(uuid.uuid4()), required=True, readonly=True, copy=False, index=True)
    agent_id = fields.Many2one("codestra.agent.profile", required=True, ondelete="restrict", index=True)
    campaign_id = fields.Many2one("call.center.campaign", ondelete="restrict", index=True)
    state = fields.Selection(AGENT_STATES, required=True, index=True)
    started_at = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True, index=True)
    ended_at = fields.Datetime(readonly=True, index=True)
    duration_seconds = fields.Integer(compute="_compute_duration", store=True, readonly=True)
    source_system = fields.Char(default="odoo", required=True)
    correlation_id = fields.Char(default=lambda self: str(uuid.uuid4()), required=True, index=True)
    _uuid_unique = models.Constraint("unique(event_uuid)", "Agent state event UUID must be unique.")

    @api.depends("started_at", "ended_at")
    def _compute_duration(self):
        now_value = fields.Datetime.now()
        for record in self:
            record.duration_seconds = max(0, int(((record.ended_at or now_value) - record.started_at).total_seconds())) if record.started_at else 0

    @api.model
    def transition(self, agent, state, campaign=None, correlation_id=None):
        if state not in dict(AGENT_STATES):
            raise ValidationError("Unknown agent state.")
        current = self.search([("agent_id", "=", agent.id), ("ended_at", "=", False)], limit=1)
        if current:
            current.write({"ended_at": fields.Datetime.now()})
        return self.create({"agent_id": agent.id, "campaign_id": campaign.id if campaign else False,
                            "state": state, "correlation_id": correlation_id or str(uuid.uuid4())})

    def unlink(self):
        raise AccessError("Agent state history is retained for audit.")


class WorkforceShift(models.Model):
    _name = "codestra.workforce.shift"
    _description = "Contact Center Workforce Shift"

    shift_uuid = fields.Char(default=lambda self: str(uuid.uuid4()), required=True, readonly=True, copy=False, index=True)
    agent_id = fields.Many2one("codestra.agent.profile", required=True, ondelete="restrict", index=True)
    campaign_id = fields.Many2one("call.center.campaign", required=True, ondelete="restrict", index=True)
    scheduled_start = fields.Datetime(required=True, index=True)
    scheduled_end = fields.Datetime(required=True, index=True)
    timezone = fields.Char(required=True, default="UTC")
    break_minutes = fields.Integer(default=0)
    state = fields.Selection([(x, x.title()) for x in ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "ABSENT", "CANCELLED")], default="SCHEDULED", required=True, index=True)
    actual_login_at = fields.Datetime()
    actual_logout_at = fields.Datetime()
    adherence_percent = fields.Float(compute="_compute_adherence", store=True)
    _uuid_unique = models.Constraint("unique(shift_uuid)", "Shift UUID must be unique.")

    @api.constrains("scheduled_start", "scheduled_end", "campaign_id", "agent_id")
    def _validate_shift(self):
        for record in self:
            if record.scheduled_end <= record.scheduled_start:
                raise ValidationError("Shift end must follow shift start.")
            if record.campaign_id not in record.agent_id.campaign_ids:
                raise ValidationError("Shift agent is not assigned to the shift campaign.")

    @api.depends("scheduled_start", "scheduled_end", "actual_login_at", "actual_logout_at")
    def _compute_adherence(self):
        for record in self:
            scheduled = (record.scheduled_end - record.scheduled_start).total_seconds() if record.scheduled_start and record.scheduled_end else 0
            actual = (record.actual_logout_at - record.actual_login_at).total_seconds() if record.actual_login_at and record.actual_logout_at else 0
            record.adherence_percent = min(100.0, max(0.0, 100.0 * actual / scheduled)) if scheduled else 0.0


class CampaignKnowledgeArticle(models.Model):
    _name = "codestra.campaign.knowledge.article"
    _description = "Campaign-Aware Knowledge Article"

    title = fields.Char(required=True)
    article_type = fields.Selection([(x, x.replace("_", " ").title()) for x in ("SCRIPT", "FAQ", "POLICY", "PROCEDURE", "DISCLOSURE", "OBJECTION", "ESCALATION", "PRODUCT", "KNOWLEDGE")], required=True, index=True)
    campaign_ids = fields.Many2many(
        "call.center.campaign", "codestra_knowledge_campaign_rel",
        "article_id", "campaign_id", required=True,
    )
    status_ids = fields.Many2many(
        "codestra.campaign.status", "codestra_knowledge_status_rel",
        "article_id", "status_id",
    )
    case_types = fields.Json(default=list)
    body = fields.Html(required=True, sanitize=True)
    version = fields.Integer(default=1, required=True)
    active = fields.Boolean(default=True)
    approved_by_id = fields.Many2one("res.users", ondelete="restrict")
    approved_at = fields.Datetime()
    retention_policy = fields.Char(default="corporate-knowledge-default", required=True)


class DataQualityIssue(models.Model):
    _name = "codestra.data.quality.issue"
    _description = "CRM Data Quality Issue"
    _order = "detected_at desc"

    issue_uuid = fields.Char(default=lambda self: str(uuid.uuid4()), required=True, readonly=True, copy=False, index=True)
    issue_type = fields.Selection([(x, x.replace("_", " ").title()) for x in ("DUPLICATE", "INVALID_PHONE", "INVALID_EMAIL", "MISSING_REQUIRED_DATA", "STALE_LEAD", "UNWORKED_LEAD", "ORPHAN_ASSIGNMENT")], required=True, index=True)
    campaign_id = fields.Many2one("call.center.campaign", ondelete="restrict", index=True)
    lead_id = fields.Many2one("crm.lead", ondelete="cascade", index=True)
    state = fields.Selection([(x, x.title()) for x in ("OPEN", "REVIEWED", "RESOLVED", "WAIVED")], default="OPEN", required=True, index=True)
    safe_detail = fields.Json(default=dict)
    detected_at = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True, index=True)
    resolved_at = fields.Datetime(readonly=True)
    correlation_id = fields.Char(default=lambda self: str(uuid.uuid4()), required=True, index=True)
    _uuid_unique = models.Constraint("unique(issue_uuid)", "Data quality issue UUID must be unique.")


class ContactPolicyService(models.AbstractModel):
    _name = "codestra.contact.policy.service"
    _description = "Fail-Closed Corporate Contact Policy"

    @api.model
    def evaluate(self, lead, channel, occurred_at=None):
        lead.ensure_one()
        now_value = fields.Datetime.to_datetime(occurred_at or fields.Datetime.now())
        if channel not in {"VOICE", "EMAIL", "SMS"}:
            return {"contact_allowed": False, "reason": "UNSUPPORTED_CHANNEL"}
        if not lead.call_center_campaign_id or lead.migration_review_required:
            return {"contact_allowed": False, "reason": "UNRESOLVED_CAMPAIGN"}
        dnc_status = lead["dnc_status"] if "dnc_status" in lead._fields else False
        if getattr(lead, "do_not_call", False) or dnc_status in {True, "blocked"}:
            return {"contact_allowed": False, "reason": "DNC"}
        consent_field = {
            "SMS": "codestra_sms_consent", "EMAIL": "codestra_email_marketing_consent",
        }.get(channel)
        provider_consent = bool(lead[consent_field]) if consent_field in lead._fields else False
        consent_channel = channel.lower()
        ledger_consent = bool(lead.consent_ids.filtered(
            lambda row: row.channel == consent_channel and row.status == "granted"
            and (not row.expires_at or row.expires_at > fields.Datetime.now())
        )) if "consent_ids" in lead._fields else False
        if channel in {"SMS", "EMAIL"} and not (provider_consent or ledger_consent):
            return {"contact_allowed": False, "reason": f"{channel}_CONSENT_REQUIRED"}
        campaign = lead.call_center_campaign_id
        hour = now_value.hour + now_value.minute / 60
        if not campaign.calling_hour_start <= hour < campaign.calling_hour_end:
            return {"contact_allowed": False, "reason": "OUTSIDE_CONTACT_HOURS"}
        open_complaint = self.env["codestra.contact.center.complaint"].sudo().search_count([
            ("customer_id", "=", lead.partner_id.id), ("state", "not in", ("RESOLVED", "CLOSED")),
            ("compliance_relevance", "=", True),
        ]) if lead.partner_id else 0
        if open_complaint:
            return {"contact_allowed": False, "reason": "COMPLIANCE_COMPLAINT_HOLD"}
        return {"contact_allowed": True, "reason": "POLICY_PASS"}
