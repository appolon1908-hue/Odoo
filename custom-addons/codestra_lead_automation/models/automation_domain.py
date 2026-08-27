from __future__ import annotations

import hashlib
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
from psycopg2 import IntegrityError

ACTIONS = [
    ("CREATE_LEAD", "Create Lead"),
    ("UPDATE_ALLOWLISTED_FIELDS", "Update Allowlisted Fields"),
    ("ASSIGN_AUTHORIZED_TEAM", "Assign Authorized Team"),
    ("ASSIGN_AUTHORIZED_USER", "Assign Authorized User"),
    ("CHANGE_AUTHORIZED_STAGE", "Change Authorized Stage"),
    ("CREATE_INTERNAL_CALLBACK_ACTIVITY", "Create Internal Callback Activity"),
]
CHANNELS = [("phone", "Phone"), ("email", "Email"), ("sms", "SMS"), ("internal", "Internal")]
STATES = [
    ("DRAFT", "Draft"), ("VALIDATING", "Validating"),
    ("POLICY_EVALUATING", "Policy Evaluating"), ("POLICY_ALLOWED", "Policy Allowed"),
    ("POLICY_DENIED", "Policy Denied"), ("CONSENT_BLOCKED", "Consent Blocked"),
    ("DNC_BLOCKED", "DNC Blocked"), ("ELIGIBLE", "Eligible"),
    ("OUTBOX_PENDING", "Outbox Pending"), ("DISPATCH_RESERVED", "Dispatch Reserved"),
    ("DISPATCHED", "Dispatched"), ("RESULT_RECEIVED", "Result Received"),
    ("RESULT_VALIDATED", "Result Validated"), ("APPLY_PENDING", "Apply Pending"),
    ("APPLIED", "Applied"), ("COMPLETED", "Completed"),
    ("RETRY_PENDING", "Retry Pending"), ("QUARANTINED", "Quarantined"),
    ("FAILED", "Failed"), ("CANCELLED", "Cancelled"),
]
TERMINAL = {"POLICY_DENIED", "CONSENT_BLOCKED", "DNC_BLOCKED", "COMPLETED", "QUARANTINED", "FAILED", "CANCELLED"}
TRANSITIONS = {
    "DRAFT": {"VALIDATING", "CANCELLED"},
    "VALIDATING": {"POLICY_EVALUATING", "QUARANTINED", "FAILED", "CANCELLED"},
    "POLICY_EVALUATING": {"POLICY_ALLOWED", "POLICY_DENIED", "CONSENT_BLOCKED", "DNC_BLOCKED", "FAILED", "CANCELLED"},
    "POLICY_ALLOWED": {"ELIGIBLE", "CONSENT_BLOCKED", "DNC_BLOCKED", "CANCELLED"},
    "ELIGIBLE": {"OUTBOX_PENDING", "CONSENT_BLOCKED", "DNC_BLOCKED", "CANCELLED"},
    "OUTBOX_PENDING": {"DISPATCH_RESERVED", "RETRY_PENDING", "DNC_BLOCKED", "CANCELLED"},
    "DISPATCH_RESERVED": {"DISPATCHED", "RETRY_PENDING", "DNC_BLOCKED", "CANCELLED"},
    "DISPATCHED": {"RESULT_RECEIVED", "RETRY_PENDING", "QUARANTINED", "FAILED", "CANCELLED"},
    "RESULT_RECEIVED": {"RESULT_VALIDATED", "QUARANTINED", "FAILED"},
    "RESULT_VALIDATED": {"APPLY_PENDING", "QUARANTINED", "FAILED"},
    "APPLY_PENDING": {"APPLIED", "RETRY_PENDING", "QUARANTINED", "FAILED"},
    "APPLIED": {"COMPLETED", "QUARANTINED", "FAILED"},
    "RETRY_PENDING": {"OUTBOX_PENDING", "APPLY_PENDING", "QUARANTINED", "FAILED", "CANCELLED"},
}
SYSTEM_CONTEXT = "codestra_lead_automation_system"


class LeadAutomationPolicy(models.Model):
    _name = "codestra.lead.automation.policy"
    _description = "Versioned Lead Automation Policy"
    _inherit = ["mail.thread", "call.center.business.unit.mixin"]  # noqa: RUF012
    _order = "effective_from desc, id desc"

    name = fields.Char(required=True)
    campaign_id = fields.Many2one("call.center.campaign", required=True, ondelete="restrict", index=True)
    environment = fields.Selection([("test", "Test"), ("staging", "Staging"), ("production", "Production")], required=True, default="staging")
    policy_version = fields.Char(required=True, index=True)
    action = fields.Selection(ACTIONS, required=True, index=True)
    channel = fields.Selection(CHANNELS, required=True)
    purpose = fields.Char(required=True)
    decision = fields.Selection([("ALLOW", "Allow"), ("DENY", "Deny")], required=True, default="DENY")
    requires_consent = fields.Boolean(default=True, required=True)
    allowed_fields_csv = fields.Char(help="Comma-separated technical field allowlist; never payload data.")
    effective_from = fields.Datetime(required=True)
    effective_until = fields.Datetime()
    approved_by_public_id = fields.Char(required=True)
    approval_reference = fields.Char(required=True)
    active = fields.Boolean(default=False)
    _policy_scope_unique = models.Constraint(
        "unique(environment,business_unit_id,campaign_id,policy_version,action,channel,purpose)",
        "A policy version must be unique in its complete scope.",
    )

    @api.constrains("business_unit_id", "campaign_id", "effective_from", "effective_until", "policy_version")
    def _check_scope(self):
        for record in self:
            if record.campaign_id.business_unit_id != record.business_unit_id:
                raise ValidationError("Policy campaign is outside its business unit.")
            if record.effective_until and record.effective_until <= record.effective_from:
                raise ValidationError("Policy expiry must follow its effective time.")
            if not record.policy_version or len(record.policy_version) > 32:
                raise ValidationError("Policy version is invalid.")


class CampaignAutomationConfig(models.Model):
    _name = "codestra.lead.automation.config"
    _description = "Default-off Campaign Automation Configuration"
    _inherit = ["mail.thread", "call.center.business.unit.mixin"]  # noqa: RUF012

    campaign_id = fields.Many2one("call.center.campaign", required=True, ondelete="cascade", index=True)
    environment = fields.Selection([("test", "Test"), ("staging", "Staging"), ("production", "Production")], required=True, default="staging")
    enabled = fields.Boolean(default=False, required=True)
    repair_enabled = fields.Boolean(default=False, required=True)
    desired_version = fields.Integer(default=1, required=True)
    maximum_attempts = fields.Integer(default=5, required=True)
    lease_seconds = fields.Integer(default=300, required=True)
    _config_scope_unique = models.Constraint("unique(environment,business_unit_id,campaign_id)", "One automation config is allowed per scope.")

    @api.constrains("business_unit_id", "campaign_id", "desired_version", "maximum_attempts", "lease_seconds")
    def _check_config(self):
        for record in self:
            if record.campaign_id.business_unit_id != record.business_unit_id:
                raise ValidationError("Automation config is outside its business unit.")
            if min(record.desired_version, record.maximum_attempts, record.lease_seconds) < 1:
                raise ValidationError("Versions, attempts and lease seconds must be positive.")


class LeadConsentSnapshot(models.Model):
    _name = "codestra.lead.consent.snapshot"
    _description = "Immutable Consent and DNC Decision Snapshot"
    _inherit = "call.center.business.unit.mixin"
    _order = "captured_at desc, id desc"

    snapshot_public_id = fields.Char(required=True, index=True, readonly=True)
    lead_id = fields.Many2one("crm.lead", required=True, ondelete="restrict", index=True, readonly=True)
    campaign_id = fields.Many2one("call.center.campaign", required=True, ondelete="restrict", index=True, readonly=True)
    channel = fields.Selection(CHANNELS, required=True, readonly=True)
    purpose = fields.Char(required=True, readonly=True)
    consent_status = fields.Selection([("granted", "Granted"), ("denied", "Denied"), ("revoked", "Revoked"), ("expired", "Expired"), ("unknown", "Unknown")], required=True, readonly=True)
    consent_source = fields.Char(readonly=True)
    consent_timestamp = fields.Datetime(readonly=True)
    revoked_at = fields.Datetime(readonly=True)
    expires_at = fields.Datetime(readonly=True)
    dnc = fields.Boolean(default=True, required=True, readonly=True)
    dnc_source = fields.Char(readonly=True)
    dnc_timestamp = fields.Datetime(readonly=True)
    captured_at = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)
    source_evidence_hash = fields.Char(size=64, readonly=True)
    _snapshot_unique = models.Constraint("unique(snapshot_public_id)", "Consent snapshot IDs must be unique.")

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get(SYSTEM_CONTEXT):
            raise AccessError("Consent snapshots are system-controlled evidence.")
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError("Consent snapshots are immutable.")

    def unlink(self):
        raise AccessError("Consent snapshots are immutable.")

    def is_eligible(self, at_time=None):
        self.ensure_one()
        at_time = at_time or fields.Datetime.now()
        return bool(
            not self.dnc
            and self.consent_status == "granted"
            and self.consent_timestamp
            and not self.revoked_at
            and (not self.expires_at or self.expires_at > at_time)
            and self.consent_source
        )


class LeadChannelEligibility(models.Model):
    _name = "codestra.lead.channel.eligibility"
    _description = "Immutable Lead Channel Eligibility Decision"
    _inherit = "call.center.business.unit.mixin"

    eligibility_public_id = fields.Char(required=True, index=True, readonly=True)
    lead_id = fields.Many2one("crm.lead", required=True, ondelete="restrict", readonly=True)
    campaign_id = fields.Many2one("call.center.campaign", required=True, ondelete="restrict", readonly=True)
    snapshot_id = fields.Many2one("codestra.lead.consent.snapshot", required=True, ondelete="restrict", readonly=True)
    channel = fields.Selection(CHANNELS, required=True, readonly=True)
    purpose = fields.Char(required=True, readonly=True)
    eligible = fields.Boolean(default=False, readonly=True)
    reason_code = fields.Char(required=True, readonly=True)
    evaluated_at = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)
    _eligibility_unique = models.Constraint("unique(eligibility_public_id)", "Eligibility decision IDs must be unique.")


class LeadAutomationExecution(models.Model):
    _name = "codestra.lead.automation.execution"
    _description = "Lead Automation Execution State"
    _inherit = ["mail.thread", "call.center.business.unit.mixin"]  # noqa: RUF012
    _order = "create_date desc, id desc"

    automation_event_id = fields.Char(required=True, index=True, readonly=True)
    environment = fields.Selection([("test", "Test"), ("staging", "Staging"), ("production", "Production")], required=True, readonly=True)
    campaign_id = fields.Many2one("call.center.campaign", required=True, ondelete="restrict", index=True, readonly=True)
    lead_id = fields.Many2one("crm.lead", ondelete="restrict", index=True, readonly=True)
    lead_public_id = fields.Char(required=True, index=True, readonly=True)
    action = fields.Selection(ACTIONS, required=True, readonly=True)
    channel = fields.Selection(CHANNELS, required=True, readonly=True)
    desired_version = fields.Integer(required=True, readonly=True)
    policy_version = fields.Char(required=True, readonly=True)
    idempotency_key = fields.Char(required=True, size=64, index=True, readonly=True)
    request_fingerprint = fields.Char(required=True, size=64, readonly=True)
    state = fields.Selection(STATES, required=True, default="DRAFT", index=True, tracking=True)
    reason_code = fields.Char(required=True, default="CREATED", tracking=True)
    retry_count = fields.Integer(default=0, required=True, readonly=True)
    next_attempt_at = fields.Datetime(readonly=True)
    consent_snapshot_id = fields.Many2one("codestra.lead.consent.snapshot", ondelete="restrict", readonly=True)
    outbox_id = fields.Many2one("codestra.runtime.integration.outbox", ondelete="restrict", readonly=True)
    result_inbox_id = fields.Many2one("codestra.integration.result.inbox", ondelete="restrict", readonly=True)
    completed_at = fields.Datetime(readonly=True)
    _event_unique = models.Constraint("unique(environment,automation_event_id)", "Automation event IDs must be unique per environment.")
    _idempotency_unique = models.Constraint("unique(environment,idempotency_key)", "Automation idempotency keys must be unique per environment.")
    _versions_positive = models.Constraint("check(desired_version > 0 AND retry_count >= 0)", "Versions and retry counters are invalid.")

    @api.model
    def stable_idempotency_key(self, environment, business_unit_key, campaign_key, lead_public_id, action, channel, desired_version, policy_version):
        values = (environment, business_unit_key, campaign_key, lead_public_id, action, channel, str(desired_version), policy_version)
        if any(not str(value) for value in values):
            raise ValidationError("Complete scoped values are required for idempotency.")
        return hashlib.sha256("\n".join(map(str, values)).encode()).hexdigest()

    @api.model
    def get_or_create_idempotent(self, vals):
        existing = self.search([("environment", "=", vals["environment"]), ("idempotency_key", "=", vals["idempotency_key"])], limit=1)
        if existing:
            if existing.request_fingerprint != vals["request_fingerprint"]:
                raise ValidationError("Conflicting idempotent automation request.")
            return existing
        return self.create(vals)

    def transition(self, target, reason_code):
        if not self.env.context.get(SYSTEM_CONTEXT):
            raise AccessError("Execution state is integration-controlled.")
        if not reason_code or len(reason_code) > 48:
            raise ValidationError("A bounded reason code is required.")
        for record in self:
            if record.state in TERMINAL or target not in TRANSITIONS.get(record.state, set()):
                raise ValidationError(f"Invalid automation transition {record.state} -> {target}.")
            values = {"state": target, "reason_code": reason_code}
            if target in TERMINAL:
                values["completed_at"] = fields.Datetime.now()
            super(LeadAutomationExecution, record).write(values)
        return True

    def write(self, vals):
        controlled = {"state", "reason_code", "retry_count", "next_attempt_at", "consent_snapshot_id", "outbox_id", "result_inbox_id", "completed_at"}
        if controlled & set(vals) and not self.env.context.get(SYSTEM_CONTEXT):
            raise AccessError("Execution state is integration-controlled.")
        immutable = {"automation_event_id", "environment", "business_unit_id", "campaign_id", "lead_id", "lead_public_id", "action", "channel", "desired_version", "policy_version", "idempotency_key", "request_fingerprint"}
        if immutable & set(vals):
            raise AccessError("Execution identity is immutable.")
        return super().write(vals)

    def unlink(self):
        raise AccessError("Execution evidence cannot be deleted.")


class LeadAutomationNonce(models.Model):
    _name = "codestra.lead.automation.nonce"
    _description = "Persistent Lead Automation Replay Guard"

    environment = fields.Char(required=True, readonly=True)
    service_identity = fields.Char(required=True, readonly=True)
    nonce_hash = fields.Char(required=True, size=64, readonly=True)
    expires_at = fields.Datetime(required=True, readonly=True, index=True)
    _nonce_unique = models.Constraint("unique(environment,service_identity,nonce_hash)", "Signed request nonce was already used.")

    @api.model
    def consume(self, environment, identity, nonce):
        if not nonce:
            raise ValidationError("Nonce is required.")
        digest = hashlib.sha256(nonce.encode()).hexdigest()
        try:
            with self.env.cr.savepoint():
                return self.sudo().create({"environment": environment, "service_identity": identity, "nonce_hash": digest, "expires_at": fields.Datetime.now() + timedelta(minutes=10)})
        except IntegrityError as exc:
            raise ValidationError("Signed request nonce was already used.") from exc

    @api.model
    def _cron_purge_expired(self):
        return self.sudo().search([("expires_at", "<", fields.Datetime.now())]).unlink()


class LeadCallbackRequest(models.Model):
    _name = "codestra.lead.callback.request"
    _description = "Idempotent Internal Callback Activity Request"
    _inherit = "call.center.business.unit.mixin"

    request_public_id = fields.Char(required=True, index=True, readonly=True)
    idempotency_key = fields.Char(required=True, size=64, index=True, readonly=True)
    execution_id = fields.Many2one("codestra.lead.automation.execution", required=True, ondelete="restrict", readonly=True)
    lead_id = fields.Many2one("crm.lead", required=True, ondelete="restrict", readonly=True)
    campaign_id = fields.Many2one("call.center.campaign", required=True, ondelete="restrict", readonly=True)
    owner_id = fields.Many2one("res.users", required=True, ondelete="restrict", readonly=True)
    due_at = fields.Datetime(required=True, readonly=True)
    state = fields.Selection([("PENDING", "Pending"), ("CREATED", "Created"), ("DNC_BLOCKED", "DNC Blocked"), ("CANCELLED", "Cancelled"), ("FAILED", "Failed")], required=True, default="PENDING", readonly=True)
    activity_id = fields.Many2one("mail.activity", ondelete="restrict", readonly=True)
    callback_task_id = fields.Many2one("call.center.callback.task", ondelete="restrict", readonly=True)
    reason_code = fields.Char(required=True, default="REQUESTED", readonly=True)
    _callback_idem_unique = models.Constraint("unique(idempotency_key)", "Callback requests must be idempotent.")

    def write(self, vals):
        if not self.env.context.get(SYSTEM_CONTEXT):
            raise AccessError("Callback mapping is integration-controlled.")
        if set(vals) - {"state", "activity_id", "callback_task_id", "reason_code"}:
            raise ValidationError("Callback identity and ownership are immutable.")
        return super().write(vals)

    def unlink(self):
        raise AccessError("Callback evidence cannot be deleted.")


class IntegrationOutboxLeadProjection(models.Model):
    _inherit = "codestra.runtime.integration.outbox"

    lead_automation_execution_id = fields.Many2one("codestra.lead.automation.execution", ondelete="restrict", index=True, readonly=True)
    lead_public_id = fields.Char(index=True, readonly=True)
    automation_action = fields.Selection(ACTIONS, readonly=True)
    desired_version = fields.Integer(readonly=True)
    policy_version = fields.Char(readonly=True)


class IntegrationResultLeadProjection(models.Model):
    _inherit = "codestra.integration.result.inbox"

    lead_automation_execution_id = fields.Many2one("codestra.lead.automation.execution", ondelete="restrict", index=True, readonly=True)
    automation_result = fields.Selection([("APPLIED", "Applied"), ("NO_CHANGE", "No Change"), ("DENIED", "Denied"), ("CONSENT_BLOCKED", "Consent Blocked"), ("DNC_BLOCKED", "DNC Blocked"), ("QUARANTINED", "Quarantined"), ("FAILED", "Failed")], readonly=True)
    automation_result_code = fields.Char(readonly=True)
    desired_version = fields.Integer(readonly=True)
    policy_version = fields.Char(readonly=True)


class ReconciliationRunLeadProjection(models.Model):
    _inherit = "codestra.integration.reconciliation.run"

    lead_automation_read_only = fields.Boolean(default=True, required=True, readonly=True)
    lead_automation_repair_authorized = fields.Boolean(default=False, required=True, readonly=True)


class ReconciliationDriftLeadProjection(models.Model):
    _inherit = "codestra.integration.reconciliation.drift"

    lead_drift_type = fields.Selection([
        ("MISSING_RESULT", "Missing Result"), ("MISSING_ACKNOWLEDGEMENT", "Missing Acknowledgement"),
        ("STALE_RESULT", "Stale Result"), ("STATE_MISMATCH", "State Mismatch"),
        ("POLICY_MISMATCH", "Policy Mismatch"), ("CONSENT_MISMATCH", "Consent Mismatch"),
        ("DNC_MISMATCH", "DNC Mismatch"), ("MISSING_ACTIVITY", "Missing Activity"),
        ("DUPLICATE_ACTIVITY", "Duplicate Activity"), ("ORPHAN_RESULT", "Orphan Result"),
        ("ORPHAN_OUTBOX", "Orphan Outbox"),
    ], index=True, readonly=True)
