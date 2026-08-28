import hashlib
import json
from datetime import timedelta

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


POLICY_WRITE_CAPABILITY = object()
RECORDING_WRITE_CAPABILITY = object()
ACCESS_EVENT_CAPABILITY = object()
RETENTION_EVENT_CAPABILITY = object()

POLICY_CONTENT_FIELDS = {
    "retention_days",
    "encryption_required",
    "checksum_required",
    "malware_validation_required",
    "payment_pause_required",
    "redaction_required",
    "agent_coaching_replay_allowed",
    "source_reference",
}
def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value):
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _is_recording_service(user):
    return user.has_group("codestra_cc_recordings.group_cc_recording_service")


def _is_global_admin(user):
    return user.has_group("codestra_cc_security.group_cc_global_administrator")


def _is_compliance(user):
    return user.has_group("codestra_cc_security.group_cc_compliance_officer")


def _feature_enabled(env, key):
    """Read only a named safety flag without granting callers parameter access."""
    value = env["ir.config_parameter"].with_user(SUPERUSER_ID).get_param(key, "false")
    return str(value).lower() == "true"


class CcRecordingPolicy(models.Model):
    _name = "cc.recording.policy"
    _description = "Campaign Recording Policy"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "campaign_id, version desc, id desc"

    name = fields.Char(required=True)
    version = fields.Integer(required=True, default=1, copy=False)
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
        index=True,
        copy=False,
    )
    requested_by_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user, readonly=True
    )
    approved_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    activated_at = fields.Datetime(readonly=True, copy=False)
    source_reference = fields.Char(required=True)
    policy_hash = fields.Char(size=64, readonly=True, copy=False, index=True)
    retention_days = fields.Integer(required=True, default=90)
    encryption_required = fields.Boolean(required=True, default=True)
    checksum_required = fields.Boolean(required=True, default=True)
    malware_validation_required = fields.Boolean(required=True, default=True)
    payment_pause_required = fields.Boolean(required=True, default=True)
    redaction_required = fields.Boolean(required=True, default=True)
    agent_coaching_replay_allowed = fields.Boolean(required=True, default=False)
    playback_enabled = fields.Boolean(required=True, default=False, readonly=True)

    _campaign_version_unique = models.Constraint(
        "unique(campaign_id, version)", "Recording policy versions must be unique per campaign."
    )
    _one_active_policy = models.UniqueIndex(
        "(campaign_id) WHERE state = 'active'",
        "A campaign may have only one active recording policy.",
    )
    _valid_retention = models.Constraint(
        "check(retention_days > 0 and retention_days <= 3650)",
        "Recording retention must be between one day and ten years.",
    )

    def _policy_payload(self):
        self.ensure_one()
        return {
            "campaign_uuid": self.campaign_id.workspace_uuid,
            "version": self.version,
            "retention_days": self.retention_days,
            "encryption_required": self.encryption_required,
            "checksum_required": self.checksum_required,
            "malware_validation_required": self.malware_validation_required,
            "payment_pause_required": self.payment_pause_required,
            "redaction_required": self.redaction_required,
            "agent_coaching_replay_allowed": self.agent_coaching_replay_allowed,
            "playback_enabled": False,
            "source_reference": self.source_reference,
        }

    @api.model_create_multi
    def create(self, values_list):
        prepared = []
        for original in values_list:
            values = dict(original)
            forbidden = {
                "approved_by_id",
                "approved_at",
                "activated_at",
                "policy_hash",
            }.intersection(values)
            if forbidden or values.get("state", "draft") != "draft" or values.get(
                "playback_enabled", False
            ):
                raise AccessError(_("New recording policies must enter the governed draft workflow."))
            values.update(
                {
                    "state": "draft",
                    "requested_by_id": self.env.user.id,
                    "playback_enabled": False,
                }
            )
            prepared.append(values)
        records = super().create(prepared)
        records._check_fail_closed()
        return records

    def write(self, values):
        internal = self.env.context.get("_cc_recording_policy_capability") is POLICY_WRITE_CAPABILITY
        if not internal and any(policy.state != "draft" for policy in self):
            if POLICY_CONTENT_FIELDS.intersection(values) or {
                "campaign_id",
                "version",
                "state",
                "policy_hash",
                "approved_by_id",
                "approved_at",
                "activated_at",
                "playback_enabled",
            }.intersection(values):
                raise AccessError(_("Submitted recording policies are immutable."))
        result = super().write(values)
        self._check_fail_closed()
        return result

    def unlink(self):
        if any(policy.state != "draft" for policy in self):
            raise AccessError(_("Submitted recording policies are retained as evidence."))
        return super().unlink()

    def copy(self, default=None):
        raise AccessError(_("Create an explicit new recording policy version."))

    @api.constrains(
        "encryption_required",
        "checksum_required",
        "payment_pause_required",
        "playback_enabled",
    )
    def _check_fail_closed(self):
        for policy in self:
            if not policy.encryption_required or not policy.checksum_required:
                raise ValidationError(_("Encryption and checksum validation are mandatory."))
            if not policy.payment_pause_required:
                raise ValidationError(_("Payment pause/resume protection is mandatory."))
            if policy.playback_enabled:
                raise ValidationError(_("CC_ENABLE_RECORDING_PLAYBACK remains false."))

    def action_submit(self):
        for policy in self:
            if policy.state != "draft":
                raise ValidationError(_("Only draft recording policies may be submitted."))
            policy.with_context(_cc_recording_policy_capability=POLICY_WRITE_CAPABILITY).write(
                {"state": "submitted", "policy_hash": _digest(policy._policy_payload())}
            )
        return True

    def action_approve(self):
        for policy in self:
            if policy.state != "submitted":
                raise ValidationError(_("Only submitted recording policies may be approved."))
            if policy.requested_by_id == self.env.user:
                raise ValidationError(_("The policy author cannot approve the same version."))
            if policy.policy_hash != _digest(policy._policy_payload()):
                raise ValidationError(_("Recording policy content changed after submission."))
            policy.with_context(_cc_recording_policy_capability=POLICY_WRITE_CAPABILITY).write(
                {
                    "state": "approved",
                    "approved_by_id": self.env.user.id,
                    "approved_at": fields.Datetime.now(),
                }
            )
        return True

    def action_activate(self):
        for policy in self:
            if policy.state != "approved":
                raise ValidationError(_("Only approved recording policies may be activated."))
            if self.search_count(
                [("campaign_id", "=", policy.campaign_id.id), ("state", "=", "active")]
            ):
                raise ValidationError(_("Retire the active campaign policy before activation."))
            policy.with_context(_cc_recording_policy_capability=POLICY_WRITE_CAPABILITY).write(
                {"state": "active", "activated_at": fields.Datetime.now()}
            )
        return True

    def action_retire(self):
        for policy in self:
            if policy.state not in {"approved", "active"}:
                raise ValidationError(_("Only approved or active recording policies may be retired."))
            policy.with_context(_cc_recording_policy_capability=POLICY_WRITE_CAPABILITY).write(
                {"state": "retired"}
            )
        return True


class CcRecording(models.Model):
    _name = "cc.recording"
    _description = "Canonical Campaign Recording Binding"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "started_at desc, id desc"
    _rec_name = "recording_uid"

    legacy_recording_id = fields.Many2one(
        "codestra.vicidial.recording",
        required=True,
        readonly=True,
        ondelete="restrict",
        index=True,
        groups=(
            "codestra_cc_recordings.group_cc_recording_service,"
            "codestra_cc_security.group_cc_global_administrator,"
            "codestra_cc_security.group_cc_auditor"
        ),
    )
    recording_uid = fields.Char(required=True, readonly=True, copy=False, index=True)
    source_call_unique_id = fields.Char(required=True, readonly=True, copy=False, index=True)
    telephony_mapping_id = fields.Many2one(
        "cc.telephony.mapping", required=True, readonly=True, ondelete="restrict"
    )
    agent_membership_id = fields.Many2one(
        "cc.campaign.membership", required=True, readonly=True, ondelete="restrict", index=True
    )
    customer_profile_id = fields.Many2one(
        "cc.customer.profile", required=True, readonly=True, ondelete="restrict", index=True
    )
    policy_id = fields.Many2one(
        "cc.recording.policy", required=True, readonly=True, ondelete="restrict", index=True
    )
    policy_hash = fields.Char(required=True, size=64, readonly=True)
    checksum_sha256 = fields.Char(required=True, size=64, readonly=True)
    storage_reference_hash = fields.Char(required=True, size=64, readonly=True)
    started_at = fields.Datetime(readonly=True, index=True)
    duration_seconds = fields.Integer(readonly=True)
    storage_state = fields.Selection(
        [
            ("reservation_pending", "Reservation Pending"),
            ("upload_pending", "Upload Pending"),
            ("verified", "Verified"),
            ("odoo_linked", "Odoo Linked"),
            ("retention_pending", "Retention Pending"),
            ("quarantined", "Quarantined"),
            ("legal_hold", "Legal Hold"),
            ("retained", "Retained"),
            ("failed", "Failed"),
        ],
        required=True,
        readonly=True,
        index=True,
    )
    verification_state = fields.Selection(
        [("pending", "Pending"), ("verified", "Verified"), ("failed", "Failed")],
        required=True,
        default="pending",
        readonly=True,
        index=True,
    )
    malware_state = fields.Selection(
        [("pending", "Pending"), ("clean", "Clean"), ("failed", "Failed")],
        required=True,
        default="pending",
        readonly=True,
        index=True,
    )
    redaction_state = fields.Selection(
        [
            ("pending", "Pending"),
            ("not_required", "Not Required"),
            ("redacted", "Redacted"),
            ("failed", "Failed"),
        ],
        required=True,
        default="pending",
        readonly=True,
        index=True,
    )
    retention_until = fields.Datetime(required=True, readonly=True, index=True)
    legal_hold = fields.Boolean(required=True, default=False, readonly=True, index=True)
    binding_state = fields.Selection(
        [("bound", "Bound"), ("blocked", "Blocked"), ("retained", "Retained")],
        required=True,
        default="bound",
        readonly=True,
        index=True,
    )
    bound_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    access_event_ids = fields.One2many("cc.recording.access.event", "recording_id", readonly=True)
    retention_event_ids = fields.One2many(
        "cc.recording.retention.event", "recording_id", readonly=True
    )

    _legacy_recording_unique = models.Constraint(
        "unique(legacy_recording_id)", "Legacy recording metadata may be bound only once."
    )
    _recording_uid_unique = models.Constraint(
        "unique(recording_uid)", "Canonical recording UIDs must be unique."
    )
    _call_unique = models.Constraint(
        "unique(campaign_id, source_call_unique_id)",
        "A campaign call may have only one canonical recording binding.",
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_recording_write_capability") is not RECORDING_WRITE_CAPABILITY:
            raise AccessError(_("Recording bindings require the governed recording service."))
        records = super().create(values_list)
        records._check_binding()
        return records.with_env(
            records.env(context=dict(records.env.context, _cc_recording_write_capability=None))
        )

    def write(self, values):
        if self.env.context.get("_cc_recording_write_capability") is not RECORDING_WRITE_CAPABILITY:
            raise AccessError(_("Recording binding state requires a governed action."))
        result = super().write(values)
        binding_fields = {
            "campaign_id",
            "legacy_recording_id",
            "telephony_mapping_id",
            "agent_membership_id",
            "customer_profile_id",
            "policy_id",
            "policy_hash",
            "recording_uid",
            "source_call_unique_id",
            "checksum_sha256",
        }
        if binding_fields.intersection(values):
            self._check_binding()
        return result

    def unlink(self):
        raise AccessError(_("Recording bindings are retained as evidence."))

    def copy(self, default=None):
        raise AccessError(_("Recording bindings cannot be copied."))

    def export_data(self, fields_to_export, raw_data=False):
        if not (_is_global_admin(self.env.user) or self.env.user.has_group(
            "codestra_cc_security.group_cc_auditor"
        )):
            raise UserError(_("Recording export requires separately governed evidence export."))
        return super().export_data(fields_to_export, raw_data=raw_data)

    @api.constrains(
        "campaign_id",
        "legacy_recording_id",
        "telephony_mapping_id",
        "agent_membership_id",
        "customer_profile_id",
        "policy_id",
        "policy_hash",
        "recording_uid",
        "source_call_unique_id",
        "checksum_sha256",
    )
    def _check_binding(self):
        for recording in self:
            legacy = recording.legacy_recording_id
            if recording.telephony_mapping_id.campaign_id != recording.campaign_id:
                raise ValidationError(_("Telephony mapping and recording campaign differ."))
            native_ids = {
                recording.telephony_mapping_id.vicidial_campaign_id,
                recording.telephony_mapping_id.legacy_vicidial_campaign_id,
            }
            if legacy.campaign_id.campaign_id not in native_ids:
                raise ValidationError(_("Legacy recording campaign does not match the controlled mapping."))
            if recording.agent_membership_id.campaign_id != recording.campaign_id or (
                recording.agent_membership_id.state != "active"
            ):
                raise ValidationError(_("Recording agent membership must be active in the campaign."))
            if legacy.agent_id.odoo_user_id != recording.agent_membership_id.user_id:
                raise ValidationError(_("Legacy recording agent does not match the canonical membership."))
            if recording.customer_profile_id.campaign_id != recording.campaign_id:
                raise ValidationError(_("Recording customer profile belongs to another campaign."))
            if recording.policy_id.campaign_id != recording.campaign_id or (
                recording.policy_id.state != "active"
            ):
                raise ValidationError(_("Recording policy must be active in the same campaign."))
            if recording.policy_hash != recording.policy_id.policy_hash:
                raise ValidationError(_("Recording policy hash does not match the approved version."))
            if recording.recording_uid != legacy.recording_uid:
                raise ValidationError(_("Recording UID binding mismatch."))
            call_ids = {legacy.vicidial_call_id, legacy.call_id.uniqueid}
            if recording.source_call_unique_id not in call_ids:
                raise ValidationError(_("Recording call binding mismatch."))
            if recording.checksum_sha256 != legacy.sha256:
                raise ValidationError(_("Recording checksum binding mismatch."))

    @api.model
    def bind_metadata(
        self,
        *,
        legacy_recording_id,
        campaign_id,
        telephony_mapping_id,
        agent_membership_id,
        customer_profile_id,
        policy_id,
        source_call_unique_id,
    ):
        if not _is_recording_service(self.env.user):
            raise AccessError(_("Only the recording integration service may bind metadata."))
        legacy = self.env["codestra.vicidial.recording"].browse(legacy_recording_id).exists()
        campaign = self.env["cc.campaign"].browse(campaign_id).exists()
        mapping = self.env["cc.telephony.mapping"].browse(telephony_mapping_id).exists()
        membership = self.env["cc.campaign.membership"].browse(agent_membership_id).exists()
        profile = self.env["cc.customer.profile"].browse(customer_profile_id).exists()
        policy = self.env["cc.recording.policy"].browse(policy_id).exists()
        if not all((legacy, campaign, mapping, membership, profile, policy)):
            raise ValidationError(_("Recording metadata binding is incomplete."))
        existing = self.search([("legacy_recording_id", "=", legacy.id)], limit=1)
        expected = {
            "campaign_id": campaign.id,
            "telephony_mapping_id": mapping.id,
            "agent_membership_id": membership.id,
            "customer_profile_id": profile.id,
            "policy_id": policy.id,
            "source_call_unique_id": source_call_unique_id,
        }
        if existing:
            actual = {name: existing[name].id for name in expected if name != "source_call_unique_id"}
            actual["source_call_unique_id"] = existing.source_call_unique_id
            if actual != expected:
                raise ValidationError(_("Recording metadata replay changed the immutable binding."))
            return existing
        started_at = legacy.started_at or fields.Datetime.now()
        reference_hash = _digest(
            {
                "recording_uid": legacy.recording_uid,
                "object_version_id": legacy.object_version_id,
                "sha256": legacy.sha256,
            }
        )
        return self.with_context(_cc_recording_write_capability=RECORDING_WRITE_CAPABILITY).create(
            {
                **expected,
                "legacy_recording_id": legacy.id,
                "recording_uid": legacy.recording_uid,
                "policy_hash": policy.policy_hash,
                "checksum_sha256": legacy.sha256,
                "storage_reference_hash": reference_hash,
                "started_at": started_at,
                "duration_seconds": legacy.duration_seconds,
                "storage_state": legacy.storage_status,
                "verification_state": (
                    "verified" if legacy.verification_status == "verified" else "pending"
                ),
                "malware_state": "pending",
                "redaction_state": "pending" if policy.redaction_required else "not_required",
                "retention_until": fields.Datetime.to_datetime(started_at)
                + timedelta(days=policy.retention_days),
                "legal_hold": legacy.legal_hold,
            }
        )

    def action_request_playback(self, purpose="quality_review"):
        allowed_purposes = {"quality_review", "supervisor_review", "compliance_review", "coaching"}
        if purpose not in allowed_purposes:
            raise ValidationError(_("A controlled recording-access purpose is required."))
        playback_enabled = _feature_enabled(self.env, "CC_ENABLE_RECORDING_PLAYBACK")
        results = []
        for recording in self:
            reason = "recording_playback_disabled"
            if playback_enabled:
                reason = "external_playback_not_implemented"
            event = self.env["cc.recording.access.event"]._append(
                recording, purpose, "blocked", reason
            )
            results.append(
                {
                    "recording_uid": recording.recording_uid,
                    "status": "blocked",
                    "reason": reason,
                    "event_id": event.event_uuid,
                }
            )
        return results[0] if len(results) == 1 else results

    def action_apply_legal_hold(self, reason):
        if not (_is_compliance(self.env.user) or _is_global_admin(self.env.user)):
            raise AccessError(_("Only Compliance or the global administrator may apply a legal hold."))
        reason = str(reason or "").strip()
        if not reason:
            raise ValidationError(_("Legal-hold evidence requires a reason."))
        for recording in self:
            if recording.legal_hold:
                continue
            recording.with_context(_cc_recording_write_capability=RECORDING_WRITE_CAPABILITY).write(
                {"legal_hold": True, "storage_state": "legal_hold", "binding_state": "retained"}
            )
            self.env["cc.recording.retention.event"]._append(
                recording, "legal_hold_applied", reason
            )
        return True

    def action_release_legal_hold(self, reason):
        if not (_is_compliance(self.env.user) or _is_global_admin(self.env.user)):
            raise AccessError(_("Only Compliance or the global administrator may release a legal hold."))
        reason = str(reason or "").strip()
        if not reason:
            raise ValidationError(_("Legal-hold release requires a reason."))
        for recording in self:
            if not recording.legal_hold:
                continue
            recording.with_context(_cc_recording_write_capability=RECORDING_WRITE_CAPABILITY).write(
                {"legal_hold": False, "storage_state": "retained", "binding_state": "retained"}
            )
            self.env["cc.recording.retention.event"]._append(
                recording, "legal_hold_released", reason
            )
        return True


class CcRecordingAccessEvent(models.Model):
    _name = "cc.recording.access.event"
    _description = "Append-Only Recording Access Evidence"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "occurred_at desc, id desc"

    event_uuid = fields.Char(required=True, readonly=True, copy=False, index=True)
    recording_id = fields.Many2one(
        "cc.recording", required=True, readonly=True, ondelete="restrict", index=True
    )
    actor_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict", index=True
    )
    purpose = fields.Selection(
        [
            ("quality_review", "Quality Review"),
            ("supervisor_review", "Supervisor Review"),
            ("compliance_review", "Compliance Review"),
            ("coaching", "Assigned Coaching"),
        ],
        required=True,
        readonly=True,
    )
    decision = fields.Selection(
        [("blocked", "Blocked"), ("granted", "Granted")], required=True, readonly=True
    )
    reason_code = fields.Char(required=True, readonly=True)
    occurred_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)

    _event_uuid_unique = models.Constraint(
        "unique(event_uuid)", "Recording access event UUIDs must be unique."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_recording_access_capability") is not ACCESS_EVENT_CAPABILITY:
            raise AccessError(_("Recording access evidence requires the governed action."))
        return super().create(values_list).with_context(
            _cc_recording_access_capability=None
        )

    def write(self, values):
        raise AccessError(_("Recording access evidence is immutable."))

    def unlink(self):
        raise AccessError(_("Recording access evidence cannot be deleted."))

    @api.model
    def _append(self, recording, purpose, decision, reason_code):
        recording.ensure_one()
        event_uuid = hashlib.sha256(
            f"{recording.recording_uid}:{self.env.user.id}:{purpose}:{fields.Datetime.now()}".encode(
                "utf-8"
            )
        ).hexdigest()
        return self.with_context(_cc_recording_access_capability=ACCESS_EVENT_CAPABILITY).create(
            {
                "campaign_id": recording.campaign_id.id,
                "event_uuid": event_uuid,
                "recording_id": recording.id,
                "actor_id": self.env.user.id,
                "purpose": purpose,
                "decision": decision,
                "reason_code": reason_code,
            }
        )


class CcRecordingRetentionEvent(models.Model):
    _name = "cc.recording.retention.event"
    _description = "Append-Only Recording Retention Evidence"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "occurred_at desc, id desc"

    event_uuid = fields.Char(required=True, readonly=True, copy=False, index=True)
    recording_id = fields.Many2one(
        "cc.recording", required=True, readonly=True, ondelete="restrict", index=True
    )
    actor_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict", index=True
    )
    event_type = fields.Selection(
        [
            ("legal_hold_applied", "Legal Hold Applied"),
            ("legal_hold_released", "Legal Hold Released"),
            ("retention_reconciled", "Retention Reconciled"),
        ],
        required=True,
        readonly=True,
    )
    reason_hash = fields.Char(required=True, size=64, readonly=True)
    occurred_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)

    _event_uuid_unique = models.Constraint(
        "unique(event_uuid)", "Recording retention event UUIDs must be unique."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_recording_retention_capability") is not RETENTION_EVENT_CAPABILITY:
            raise AccessError(_("Recording retention evidence requires the governed action."))
        return super().create(values_list).with_context(
            _cc_recording_retention_capability=None
        )

    def write(self, values):
        raise AccessError(_("Recording retention evidence is immutable."))

    def unlink(self):
        raise AccessError(_("Recording retention evidence cannot be deleted."))

    @api.model
    def _append(self, recording, event_type, reason):
        recording.ensure_one()
        event_uuid = hashlib.sha256(
            f"{recording.recording_uid}:{event_type}:{fields.Datetime.now()}".encode("utf-8")
        ).hexdigest()
        return self.with_context(
            _cc_recording_retention_capability=RETENTION_EVENT_CAPABILITY
        ).create(
            {
                "campaign_id": recording.campaign_id.id,
                "event_uuid": event_uuid,
                "recording_id": recording.id,
                "actor_id": self.env.user.id,
                "event_type": event_type,
                "reason_hash": hashlib.sha256(reason.encode("utf-8")).hexdigest(),
            }
        )


class LegacyRecordingPlaybackGuard(models.Model):
    _inherit = "codestra.vicidial.recording"

    def action_play_recording(self):
        enabled = _feature_enabled(self.env, "CC_ENABLE_RECORDING_PLAYBACK")
        if not enabled:
            raise UserError(_("CC_ENABLE_RECORDING_PLAYBACK is false; playback is blocked."))
        return super().action_play_recording()
