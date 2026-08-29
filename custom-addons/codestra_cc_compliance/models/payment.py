import uuid

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .policy import (
    digest,
    hash_text,
    is_compliance,
    is_compliance_service,
    is_global_admin,
    require_campaign_access,
    valid_sha256,
)


PAYMENT_SESSION_CAPABILITY = object()
PAYMENT_EVENT_CAPABILITY = object()


def _is_recording_service(user):
    return user.has_group("codestra_cc_recordings.group_cc_recording_service")


def _can_record_payment_evidence(user):
    return (
        is_global_admin(user)
        or is_compliance(user)
        or is_compliance_service(user)
        or _is_recording_service(user)
    )


class CcPaymentSafetySession(models.Model):
    _name = "cc.payment.safety.session"
    _description = "Tokenized Payment and Recording-Pause Workflow"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "requested_at desc, id desc"

    payment_uuid = fields.Char(required=True, readonly=True, copy=False, index=True)
    idempotency_key = fields.Char(required=True, readonly=True, copy=False, index=True)
    policy_id = fields.Many2one(
        "cc.compliance.policy", required=True, readonly=True, ondelete="restrict", index=True
    )
    customer_profile_id = fields.Many2one(
        "cc.customer.profile", required=True, readonly=True, ondelete="restrict", index=True
    )
    agent_membership_id = fields.Many2one(
        "cc.campaign.membership", required=True, readonly=True, ondelete="restrict", index=True
    )
    call_unique_id = fields.Char(required=True, readonly=True, index=True)
    recording_id = fields.Many2one("cc.recording", readonly=True, ondelete="restrict", index=True)
    state = fields.Selection(
        [
            ("pause_required", "Recording Pause Required"),
            ("paused", "Recording Paused"),
            ("tokenized_handoff", "Tokenized Handoff Recorded"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="pause_required",
        readonly=True,
        index=True,
    )
    requested_by_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict"
    )
    requested_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True, index=True
    )
    paused_at = fields.Datetime(readonly=True)
    tokenized_handoff_at = fields.Datetime(readonly=True)
    completed_at = fields.Datetime(readonly=True)
    cancelled_at = fields.Datetime(readonly=True)
    provider_reference_hash = fields.Char(readonly=True, size=64)
    tokenization_evidence_hash = fields.Char(readonly=True, size=64)
    final_evidence_hash = fields.Char(readonly=True, size=64, index=True)
    event_ids = fields.One2many(
        "cc.payment.safety.event", "payment_session_id", readonly=True
    )

    _payment_uuid_unique = models.Constraint(
        "unique(payment_uuid)", "Payment workflow UUIDs must be unique."
    )
    _idempotency_unique = models.Constraint(
        "unique(idempotency_key)", "Payment workflow idempotency keys must be unique."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_payment_session_capability") is not PAYMENT_SESSION_CAPABILITY:
            raise AccessError(_("Payment workflow requires the governed entry point."))
        records = super().create(values_list)
        return records.with_env(
            records.env(context=dict(records.env.context, _cc_payment_session_capability=None))
        )

    def write(self, values):
        if self.env.context.get("_cc_payment_session_capability") is not PAYMENT_SESSION_CAPABILITY:
            raise AccessError(_("Payment workflow state is service-managed."))
        return super().write(values)

    def unlink(self):
        raise AccessError(_("Payment-safety evidence cannot be deleted."))

    @api.model
    def begin_session(
        self, *, policy, customer_profile, call_unique_id, idempotency_key
    ):
        policy = self.env["cc.compliance.policy"].browse(
            getattr(policy, "id", policy)
        ).exists()
        profile = self.env["cc.customer.profile"].browse(
            getattr(customer_profile, "id", customer_profile)
        ).exists()
        if not policy or not profile or policy.state != "active":
            raise ValidationError(_("Payment workflow requires an active compliance policy."))
        campaign = require_campaign_access(
            self.env,
            profile.campaign_id,
            roles=("agent", "senior_agent", "supervisor"),
        )
        if policy.campaign_id != campaign or not call_unique_id:
            raise ValidationError(_("Payment policy, customer, and call must share a campaign."))
        if not (
            policy.secure_payment_link_required
            and policy.payment_tokenization_required
            and policy.payment_recording_pause_required
            and not policy.direct_payment_capture_allowed
        ):
            raise ValidationError(_("The active payment policy is not fail-closed."))
        membership = self.env["cc.campaign.membership"].search(
            [
                ("campaign_id", "=", campaign.id),
                ("user_id", "=", self.env.user.id),
                ("state", "=", "active"),
                ("role", "in", ("agent", "senior_agent", "supervisor")),
            ],
            limit=1,
        )
        if not membership:
            raise AccessError(_("Payment workflow requires an active operational membership."))
        existing = self.search([("idempotency_key", "=", idempotency_key)], limit=1)
        if existing:
            if (
                existing.policy_id != policy
                or existing.customer_profile_id != profile
                or existing.call_unique_id != call_unique_id
                or existing.agent_membership_id != membership
            ):
                raise ValidationError(_("Payment workflow replay changed immutable binding."))
            return existing
        values = {
            "campaign_id": campaign.id,
            "payment_uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"cc-payment:{idempotency_key}")),
            "idempotency_key": idempotency_key,
            "policy_id": policy.id,
            "customer_profile_id": profile.id,
            "agent_membership_id": membership.id,
            "call_unique_id": call_unique_id,
            "state": "pause_required",
            "requested_by_id": self.env.user.id,
            "requested_at": fields.Datetime.now(),
        }
        session = self.with_context(
            _cc_payment_session_capability=PAYMENT_SESSION_CAPABILITY
        ).create(values)
        self.env["cc.payment.safety.event"]._append(
            session, "pause_required", "payment_recording_pause_required"
        )
        return session

    def action_record_pause(self, *, evidence_reference, recording=False):
        if not _can_record_payment_evidence(self.env.user):
            raise AccessError(_("Only the protected payment/recording service may confirm pause."))
        for session in self:
            if session.state != "pause_required":
                raise ValidationError(_("Recording pause is not pending."))
            recording_record = self.env["cc.recording"].browse(
                getattr(recording, "id", recording)
            ).exists() if recording else self.env["cc.recording"]
            if recording_record and recording_record.campaign_id != session.campaign_id:
                raise ValidationError(_("Recording and payment workflow campaigns differ."))
            session.with_context(_cc_payment_session_capability=PAYMENT_SESSION_CAPABILITY).write(
                {
                    "state": "paused",
                    "paused_at": fields.Datetime.now(),
                    "recording_id": recording_record.id or False,
                }
            )
            self.env["cc.payment.safety.event"]._append(
                session, "paused", evidence_reference
            )
        return True

    def action_record_tokenized_handoff(
        self, *, provider_reference_hash, tokenization_evidence_hash
    ):
        if not _can_record_payment_evidence(self.env.user):
            raise AccessError(_("Only the protected payment service may record tokenized handoff."))
        if not valid_sha256(provider_reference_hash) or not valid_sha256(
            tokenization_evidence_hash
        ):
            raise ValidationError(_("Payment provider references must be protected SHA-256 values."))
        for session in self:
            if session.state != "paused":
                raise ValidationError(_("Recording must be paused before tokenized handoff."))
            session.with_context(_cc_payment_session_capability=PAYMENT_SESSION_CAPABILITY).write(
                {
                    "state": "tokenized_handoff",
                    "tokenized_handoff_at": fields.Datetime.now(),
                    "provider_reference_hash": provider_reference_hash.lower(),
                    "tokenization_evidence_hash": tokenization_evidence_hash.lower(),
                }
            )
            self.env["cc.payment.safety.event"]._append(
                session, "tokenized_handoff", tokenization_evidence_hash
            )
        return True

    def action_complete(self, *, evidence_reference):
        if not _can_record_payment_evidence(self.env.user):
            raise AccessError(_("Only the protected payment service may complete workflow."))
        for session in self:
            if session.state != "tokenized_handoff":
                raise ValidationError(_("Tokenized handoff must precede completion."))
            completed_at = fields.Datetime.now()
            final_hash = digest(
                {
                    "payment_uuid": session.payment_uuid,
                    "policy_hash": session.policy_id.policy_hash,
                    "call_unique_id": session.call_unique_id,
                    "provider_reference_hash": session.provider_reference_hash,
                    "tokenization_evidence_hash": session.tokenization_evidence_hash,
                    "completed_at": completed_at,
                    "completion_reference_hash": hash_text(evidence_reference),
                }
            )
            session.with_context(_cc_payment_session_capability=PAYMENT_SESSION_CAPABILITY).write(
                {
                    "state": "completed",
                    "completed_at": completed_at,
                    "final_evidence_hash": final_hash,
                }
            )
            self.env["cc.payment.safety.event"]._append(
                session, "completed", evidence_reference
            )
        return True

    def action_cancel(self, *, reason):
        for session in self:
            if self.env.user != session.requested_by_id and not _can_record_payment_evidence(
                self.env.user
            ):
                raise AccessError(_("Only the requester or protected service may cancel."))
            if session.state in {"completed", "cancelled"}:
                raise ValidationError(_("Final payment workflow cannot change."))
            session.with_context(_cc_payment_session_capability=PAYMENT_SESSION_CAPABILITY).write(
                {"state": "cancelled", "cancelled_at": fields.Datetime.now()}
            )
            self.env["cc.payment.safety.event"]._append(session, "cancelled", reason)
        return True


class CcPaymentSafetyEvent(models.Model):
    _name = "cc.payment.safety.event"
    _description = "Append-Only Payment Safety Timeline"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "occurred_at, id"

    event_uuid = fields.Char(required=True, readonly=True, copy=False, index=True)
    payment_session_id = fields.Many2one(
        "cc.payment.safety.session", required=True, readonly=True, ondelete="restrict", index=True
    )
    event_type = fields.Selection(
        [
            ("pause_required", "Recording Pause Required"),
            ("paused", "Recording Paused"),
            ("tokenized_handoff", "Tokenized Handoff"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        readonly=True,
        index=True,
    )
    actor_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict", index=True
    )
    occurred_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True, index=True
    )
    reason_hash = fields.Char(required=True, readonly=True, size=64)
    previous_hash = fields.Char(required=True, readonly=True, size=64)
    evidence_hash = fields.Char(required=True, readonly=True, size=64, index=True)

    _event_uuid_unique = models.Constraint(
        "unique(event_uuid)", "Payment safety event UUIDs must be unique."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_payment_event_capability") is not PAYMENT_EVENT_CAPABILITY:
            raise AccessError(_("Payment timeline requires the governed workflow."))
        records = super().create(values_list)
        return records.with_env(
            records.env(context=dict(records.env.context, _cc_payment_event_capability=None))
        )

    def write(self, values):
        raise AccessError(_("Payment safety timeline is immutable."))

    def unlink(self):
        raise AccessError(_("Payment safety timeline cannot be deleted."))

    @api.model
    def _append(self, session, event_type, reason):
        session.ensure_one()
        sequence = self.search_count([("payment_session_id", "=", session.id)]) + 1
        existing = self.search(
            [("payment_session_id", "=", session.id)], order="id desc", limit=1
        )
        occurred_at = fields.Datetime.now()
        values = {
            "campaign_id": session.campaign_id.id,
            "event_uuid": str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"cc-payment-event:{session.payment_uuid}:{sequence}:{event_type}",
                )
            ),
            "payment_session_id": session.id,
            "event_type": event_type,
            "actor_id": self.env.user.id,
            "occurred_at": occurred_at,
            "reason_hash": hash_text(reason),
            "previous_hash": existing.evidence_hash or "0" * 64,
        }
        values["evidence_hash"] = digest(values)
        event = self.with_context(_cc_payment_event_capability=PAYMENT_EVENT_CAPABILITY).create(
            values
        )
        self.env["cc.audit.event"]._append_event(
            event_type=f"cc.payment.{event_type}.v1",
            action="payment_safety_transition",
            result="success",
            target_model=session._name,
            target_record_id=session.id,
            idempotency_key=f"payment:{session.id}:{sequence}:{event_type}",
            campaign=session.campaign_id,
            reason_code=event_type,
            reason=reason,
            metadata={"payment_uuid": session.payment_uuid, "evidence_hash": event.evidence_hash},
        )
        return event
