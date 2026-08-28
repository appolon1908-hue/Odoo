import hashlib
import json
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from odoo.addons.codestra_cc_audit.models.audit import AUDIT_APPEND_CAPABILITY


POLICY_WRITE_CAPABILITY = object()
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def hash_text(value):
    normalized = str(value or "").strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else False


def valid_sha256(value):
    return bool(SHA256_PATTERN.fullmatch(str(value or "").lower()))


def is_global_admin(user):
    return user.has_group("codestra_cc_security.group_cc_global_administrator")


def is_configuration_manager(user):
    return user.has_group(
        "codestra_cc_security.group_cc_campaign_configuration_manager"
    )


def is_compliance(user):
    return user.has_group("codestra_cc_security.group_cc_compliance_officer")


def is_compliance_service(user):
    return user.has_group("codestra_cc_compliance.group_cc_compliance_event_service")


def is_operational(user):
    return any(
        user.has_group(xmlid)
        for xmlid in (
            "codestra_cc_security.group_cc_campaign_agent",
            "codestra_cc_security.group_cc_senior_agent",
            "codestra_cc_security.group_cc_campaign_supervisor",
        )
    )


def validate_timezone(value):
    try:
        return ZoneInfo(str(value or ""))
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationError(_("A valid IANA customer time zone is required."))


def require_campaign_access(env, campaign, roles=None):
    campaign = env["cc.campaign"].browse(getattr(campaign, "id", campaign)).exists()
    if not campaign:
        raise ValidationError(_("A canonical campaign workspace is required."))
    if is_global_admin(env.user) or is_compliance_service(env.user):
        return campaign
    if is_operational(env.user):
        membership = env.user._cc_resolve_operational_membership()
        if membership.campaign_id != campaign:
            raise AccessError(_("The active membership determines compliance scope."))
        if roles and membership.role not in roles:
            raise AccessError(_("The active role cannot perform this compliance action."))
        return campaign
    domain = [
        ("campaign_id", "=", campaign.id),
        ("user_id", "=", env.user.id),
        ("state", "=", "active"),
    ]
    if roles:
        domain.append(("role", "in", tuple(roles)))
    if not env["cc.campaign.membership"].search(domain, limit=1):
        raise AccessError(_("An active campaign assignment is required."))
    return campaign


class CcCompliancePolicy(models.Model):
    _name = "cc.compliance.policy"
    _description = "Versioned Campaign Compliance Policy"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "campaign_id, version desc, id desc"

    name = fields.Char(required=True)
    version = fields.Integer(required=True, default=1, readonly=True, copy=False)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("approved", "Approved"),
            ("active", "Active"),
            ("retired", "Retired"),
        ],
        required=True,
        default="draft",
        readonly=True,
        index=True,
        copy=False,
    )
    jurisdiction_code = fields.Char(required=True, index=True)
    channel = fields.Selection(
        [("phone", "Phone"), ("email", "Email"), ("sms", "SMS"), ("all", "All")],
        required=True,
        default="phone",
        index=True,
    )
    source_reference = fields.Char(required=True, readonly=True)
    consent_required = fields.Boolean(required=True, default=True)
    consent_text_version = fields.Char(required=True)
    allowed_weekdays = fields.Json(default=lambda self: [0, 1, 2, 3, 4])
    calling_hour_start = fields.Float(required=True, default=9.0)
    calling_hour_end = fields.Float(required=True, default=17.0)
    customer_timezone_required = fields.Boolean(required=True, default=True)
    suppression_latency_seconds = fields.Integer(required=True, default=0)
    automated_outreach_allowed = fields.Boolean(required=True, default=False, readonly=True)
    predictive_dialing_allowed = fields.Boolean(required=True, default=False, readonly=True)
    ai_voice_allowed = fields.Boolean(required=True, default=False, readonly=True)
    prerecorded_voice_allowed = fields.Boolean(required=True, default=False, readonly=True)
    secure_payment_link_required = fields.Boolean(required=True, default=True)
    payment_tokenization_required = fields.Boolean(required=True, default=True)
    payment_recording_pause_required = fields.Boolean(required=True, default=True)
    direct_payment_capture_allowed = fields.Boolean(required=True, default=False, readonly=True)
    agent_bulk_export_allowed = fields.Boolean(required=True, default=False, readonly=True)
    supervisor_bulk_export_allowed = fields.Boolean(required=True, default=False, readonly=True)
    crm_retention_days = fields.Integer(required=True, default=730)
    mail_retention_days = fields.Integer(required=True, default=365)
    recording_retention_days = fields.Integer(required=True, default=90)
    consent_retention_days = fields.Integer(required=True, default=1825)
    audit_retention_days = fields.Integer(required=True, default=2555)
    author_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict"
    )
    approver_id = fields.Many2one(
        "res.users", readonly=True, copy=False, ondelete="restrict"
    )
    approved_at = fields.Datetime(readonly=True, copy=False)
    activated_at = fields.Datetime(readonly=True, copy=False)
    policy_hash = fields.Char(readonly=True, copy=False, size=64, index=True)

    _campaign_version_unique = models.Constraint(
        "unique(campaign_id, version)",
        "Compliance policy versions must be unique per campaign.",
    )
    _one_active_policy = models.UniqueIndex(
        "(campaign_id, channel) WHERE state = 'active'",
        "A campaign may have only one active compliance policy per channel.",
    )
    _valid_hours = models.Constraint(
        "check(calling_hour_start >= 0 and calling_hour_start < calling_hour_end and calling_hour_end <= 24)",
        "Calling hours must be ordered inside one local day.",
    )
    _immediate_suppression = models.Constraint(
        "check(suppression_latency_seconds = 0)",
        "DNC and revocation suppression must be immediate.",
    )

    def _payload(self):
        self.ensure_one()
        return {
            "campaign_uuid": self.campaign_id.workspace_uuid,
            "version": self.version,
            "jurisdiction_code": self.jurisdiction_code,
            "channel": self.channel,
            "source_reference": self.source_reference,
            "consent_required": self.consent_required,
            "consent_text_version": self.consent_text_version,
            "allowed_weekdays": self.allowed_weekdays,
            "calling_hour_start": self.calling_hour_start,
            "calling_hour_end": self.calling_hour_end,
            "customer_timezone_required": self.customer_timezone_required,
            "suppression_latency_seconds": self.suppression_latency_seconds,
            "automated_outreach_allowed": False,
            "predictive_dialing_allowed": False,
            "ai_voice_allowed": False,
            "prerecorded_voice_allowed": False,
            "secure_payment_link_required": self.secure_payment_link_required,
            "payment_tokenization_required": self.payment_tokenization_required,
            "payment_recording_pause_required": self.payment_recording_pause_required,
            "direct_payment_capture_allowed": False,
            "agent_bulk_export_allowed": False,
            "supervisor_bulk_export_allowed": False,
            "retention_days": {
                "crm": self.crm_retention_days,
                "mail": self.mail_retention_days,
                "recording": self.recording_retention_days,
                "consent": self.consent_retention_days,
                "audit": self.audit_retention_days,
            },
        }

    @api.model_create_multi
    def create(self, values_list):
        if not (is_global_admin(self.env.user) or is_configuration_manager(self.env.user)):
            raise AccessError(_("Only campaign configuration may draft compliance policy."))
        prepared = []
        for original in values_list:
            values = dict(original)
            if values.get("state", "draft") != "draft":
                raise ValidationError(_("Compliance policy must be created in draft."))
            values["author_id"] = self.env.user.id
            values["jurisdiction_code"] = str(values.get("jurisdiction_code", "")).strip().upper()
            for field_name in (
                "automated_outreach_allowed",
                "predictive_dialing_allowed",
                "ai_voice_allowed",
                "prerecorded_voice_allowed",
                "direct_payment_capture_allowed",
                "agent_bulk_export_allowed",
                "supervisor_bulk_export_allowed",
            ):
                if values.get(field_name):
                    raise ValidationError(_("Live and bulk-export capabilities remain disabled."))
                values[field_name] = False
            prepared.append(values)
        records = super().create(prepared)
        records._check_policy_safety()
        return records

    def write(self, values):
        internal = self.env.context.get("_cc_compliance_policy_capability") is POLICY_WRITE_CAPABILITY
        if not internal and ("state" in values or any(row.state != "draft" for row in self)):
            raise AccessError(_("Submitted compliance policy is immutable."))
        if not internal and not (
            is_global_admin(self.env.user) or is_configuration_manager(self.env.user)
        ):
            raise AccessError(_("Only campaign configuration may edit draft policy."))
        if "jurisdiction_code" in values:
            values["jurisdiction_code"] = str(values["jurisdiction_code"]).strip().upper()
        result = super().write(values)
        self._check_policy_safety()
        return result

    def unlink(self):
        if any(row.state != "draft" for row in self):
            raise AccessError(_("Submitted compliance policy is retained as evidence."))
        return super().unlink()

    def copy(self, default=None):
        raise AccessError(_("Create an explicit new compliance policy version."))

    @api.constrains(
        "allowed_weekdays",
        "customer_timezone_required",
        "automated_outreach_allowed",
        "predictive_dialing_allowed",
        "ai_voice_allowed",
        "prerecorded_voice_allowed",
        "secure_payment_link_required",
        "payment_tokenization_required",
        "payment_recording_pause_required",
        "direct_payment_capture_allowed",
        "agent_bulk_export_allowed",
        "supervisor_bulk_export_allowed",
        "crm_retention_days",
        "mail_retention_days",
        "recording_retention_days",
        "consent_retention_days",
        "audit_retention_days",
    )
    def _check_policy_safety(self):
        for policy in self:
            days = policy.allowed_weekdays or []
            if not isinstance(days, list) or not days or any(
                not isinstance(day, int) or day < 0 or day > 6 for day in days
            ):
                raise ValidationError(_("Allowed weekdays must contain values zero through six."))
            if not policy.customer_timezone_required:
                raise ValidationError(_("Customer-local calling-time evaluation is mandatory."))
            if any(
                (
                    policy.automated_outreach_allowed,
                    policy.predictive_dialing_allowed,
                    policy.ai_voice_allowed,
                    policy.prerecorded_voice_allowed,
                    policy.direct_payment_capture_allowed,
                    policy.agent_bulk_export_allowed,
                    policy.supervisor_bulk_export_allowed,
                )
            ):
                raise ValidationError(_("Live, direct-payment, and bulk-export capabilities stay false."))
            if not (
                policy.secure_payment_link_required
                and policy.payment_tokenization_required
                and policy.payment_recording_pause_required
            ):
                raise ValidationError(_("Secure link, tokenization, and recording pause are mandatory."))
            retention = (
                policy.crm_retention_days,
                policy.mail_retention_days,
                policy.recording_retention_days,
                policy.consent_retention_days,
                policy.audit_retention_days,
            )
            if any(value <= 0 or value > 3650 for value in retention):
                raise ValidationError(_("Retention periods must be one day through ten years."))

    def action_submit(self):
        for policy in self:
            if policy.state != "draft":
                raise ValidationError(_("Only draft policy may be submitted."))
            policy._check_policy_safety()
            policy.with_context(_cc_compliance_policy_capability=POLICY_WRITE_CAPABILITY).write(
                {"state": "submitted", "policy_hash": digest(policy._payload())}
            )
        return True

    def action_approve(self):
        if not (is_global_admin(self.env.user) or is_compliance(self.env.user)):
            raise AccessError(_("Global Administration or Compliance must approve policy."))
        for policy in self:
            if policy.state != "submitted":
                raise ValidationError(_("Only submitted policy may be approved."))
            if policy.author_id == self.env.user:
                raise AccessError(_("The policy author cannot approve the same version."))
            if policy.policy_hash != digest(policy._payload()):
                raise ValidationError(_("Compliance policy changed after submission."))
            policy.with_context(_cc_compliance_policy_capability=POLICY_WRITE_CAPABILITY).write(
                {
                    "state": "approved",
                    "approver_id": self.env.user.id,
                    "approved_at": fields.Datetime.now(),
                }
            )
        return True

    def action_activate(self):
        if not (is_global_admin(self.env.user) or is_compliance(self.env.user)):
            raise AccessError(_("Global Administration or Compliance must activate policy."))
        for policy in self:
            if policy.state != "approved":
                raise ValidationError(_("Only approved policy may be activated."))
            if self.search_count(
                [
                    ("campaign_id", "=", policy.campaign_id.id),
                    ("channel", "=", policy.channel),
                    ("state", "=", "active"),
                ]
            ):
                raise ValidationError(_("Retire the active campaign/channel policy first."))
            policy.with_context(_cc_compliance_policy_capability=POLICY_WRITE_CAPABILITY).write(
                {"state": "active", "activated_at": fields.Datetime.now()}
            )
            self.env["cc.audit.event"]._append_event(
                event_type="cc.compliance.policy.activated.v1",
                action="compliance_policy_activate",
                result="success",
                target_model=policy._name,
                target_record_id=policy.id,
                idempotency_key=f"compliance-policy:{policy.id}:activated",
                campaign=policy.campaign_id,
                reason_code="separately_approved_policy",
                source_reference=policy.source_reference,
                metadata={"version": policy.version, "policy_hash": policy.policy_hash},
            )
        return True

    def action_retire(self):
        if not (is_global_admin(self.env.user) or is_compliance(self.env.user)):
            raise AccessError(_("Global Administration or Compliance must retire policy."))
        for policy in self:
            if policy.state not in {"approved", "active"}:
                raise ValidationError(_("Only approved or active policy may be retired."))
            policy.with_context(_cc_compliance_policy_capability=POLICY_WRITE_CAPABILITY).write(
                {"state": "retired"}
            )
        return True


class CcCustomerProfile(models.Model):
    _inherit = "cc.customer.profile"

    contact_timezone = fields.Char(
        required=True,
        default="UTC",
        readonly=True,
        help="Protected IANA time zone used for pre-dial calling-window evaluation.",
    )

    @api.constrains("contact_timezone")
    def _check_contact_timezone(self):
        for profile in self:
            validate_timezone(profile.contact_timezone)
