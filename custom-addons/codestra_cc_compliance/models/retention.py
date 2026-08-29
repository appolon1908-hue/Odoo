import uuid
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .policy import (
    digest,
    hash_text,
    is_compliance,
    is_compliance_service,
    is_global_admin,
    require_campaign_access,
)


LEGAL_HOLD_CAPABILITY = object()
RETENTION_APPEND_CAPABILITY = object()
RETENTION_MODEL_FIELDS = {
    "crm.lead": "crm_retention_days",
    "cc.customer.profile": "crm_retention_days",
    "mail.message": "mail_retention_days",
    "cc.recording": "recording_retention_days",
    "cc.consent.evidence": "consent_retention_days",
    "cc.audit.event": "audit_retention_days",
}


def _can_govern_retention(user):
    return is_global_admin(user) or is_compliance(user) or is_compliance_service(user)


class CcLegalHold(models.Model):
    _name = "cc.legal.hold"
    _description = "Campaign Legal Hold Evidence"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "requested_at desc, id desc"

    hold_uuid = fields.Char(required=True, readonly=True, copy=False, index=True)
    idempotency_key = fields.Char(required=True, readonly=True, copy=False, index=True)
    policy_id = fields.Many2one(
        "cc.compliance.policy", required=True, readonly=True, ondelete="restrict", index=True
    )
    target_model = fields.Selection(
        [(model_name, model_name) for model_name in RETENTION_MODEL_FIELDS],
        required=True,
        readonly=True,
        index=True,
    )
    target_reference_hash = fields.Char(required=True, readonly=True, size=64, index=True)
    state = fields.Selection(
        [("requested", "Requested"), ("active", "Active"), ("released", "Released")],
        required=True,
        default="requested",
        readonly=True,
        index=True,
    )
    reason_hash = fields.Char(required=True, readonly=True, size=64)
    source_ticket_hash = fields.Char(required=True, readonly=True, size=64)
    requested_by_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict"
    )
    requested_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True, index=True
    )
    approved_by_id = fields.Many2one("res.users", readonly=True, ondelete="restrict")
    approved_at = fields.Datetime(readonly=True)
    released_by_id = fields.Many2one("res.users", readonly=True, ondelete="restrict")
    released_at = fields.Datetime(readonly=True)
    evidence_hash = fields.Char(required=True, readonly=True, size=64, index=True)
    release_evidence_hash = fields.Char(readonly=True, size=64, index=True)

    _hold_uuid_unique = models.Constraint(
        "unique(hold_uuid)", "Legal hold UUIDs must be unique."
    )
    _idempotency_unique = models.Constraint(
        "unique(idempotency_key)", "Legal hold idempotency keys must be unique."
    )
    _one_active_hold = models.UniqueIndex(
        "(campaign_id, target_model, target_reference_hash) WHERE state IN ('requested', 'active')",
        "A record may have only one open campaign legal hold.",
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_legal_hold_capability") is not LEGAL_HOLD_CAPABILITY:
            raise AccessError(_("Legal hold requires the governed request workflow."))
        records = super().create(values_list)
        return records.with_env(
            records.env(context=dict(records.env.context, _cc_legal_hold_capability=None))
        )

    def write(self, values):
        if self.env.context.get("_cc_legal_hold_capability") is not LEGAL_HOLD_CAPABILITY:
            raise AccessError(_("Legal hold changes require governed approval."))
        return super().write(values)

    def unlink(self):
        raise AccessError(_("Legal hold evidence cannot be deleted."))

    @api.model
    def request_hold(
        self,
        *,
        policy,
        target_model,
        target_reference,
        reason,
        source_ticket,
        idempotency_key,
    ):
        if not _can_govern_retention(self.env.user):
            raise AccessError(_("Only Compliance or Global Administration may request hold."))
        policy = self.env["cc.compliance.policy"].browse(
            getattr(policy, "id", policy)
        ).exists()
        if not policy or policy.state != "active":
            raise ValidationError(_("Legal hold requires an active compliance policy."))
        campaign = require_campaign_access(self.env, policy.campaign_id, roles=("compliance",))
        if target_model not in RETENTION_MODEL_FIELDS:
            raise ValidationError(_("Legal hold target model is not controlled."))
        stable = {
            "campaign_id": campaign.id,
            "policy_id": policy.id,
            "target_model": target_model,
            "target_reference_hash": hash_text(target_reference),
            "reason_hash": hash_text(reason),
            "source_ticket_hash": hash_text(source_ticket),
            "requested_by_id": self.env.user.id,
        }
        if not all(
            stable[key]
            for key in ("target_reference_hash", "reason_hash", "source_ticket_hash")
        ):
            raise ValidationError(_("Legal hold requires target, reason, and source ticket."))
        evidence_hash = digest(stable)
        existing = self.search([("idempotency_key", "=", idempotency_key)], limit=1)
        if existing:
            if existing.evidence_hash != evidence_hash:
                raise ValidationError(_("Legal hold replay changed immutable evidence."))
            return existing
        values = {
            **stable,
            "hold_uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"cc-legal-hold:{idempotency_key}")),
            "idempotency_key": idempotency_key,
            "state": "requested",
            "requested_at": fields.Datetime.now(),
            "evidence_hash": evidence_hash,
        }
        hold = self.with_context(_cc_legal_hold_capability=LEGAL_HOLD_CAPABILITY).create(
            values
        )
        return hold

    def action_activate(self):
        if not _can_govern_retention(self.env.user):
            raise AccessError(_("Only Compliance or Global Administration may approve hold."))
        for hold in self:
            require_campaign_access(self.env, hold.campaign_id, roles=("compliance",))
            if hold.state != "requested":
                raise ValidationError(_("Only requested legal hold may be activated."))
            if hold.requested_by_id == self.env.user:
                raise AccessError(_("Legal-hold requester cannot approve the same hold."))
            hold.with_context(_cc_legal_hold_capability=LEGAL_HOLD_CAPABILITY).write(
                {
                    "state": "active",
                    "approved_by_id": self.env.user.id,
                    "approved_at": fields.Datetime.now(),
                }
            )
            self.env["cc.audit.event"]._append_event(
                event_type="cc.compliance.hold.applied.v1",
                action="legal_hold_activate",
                result="success",
                target_model=hold._name,
                target_record_id=hold.id,
                idempotency_key=f"legal-hold:{hold.id}:active",
                campaign=hold.campaign_id,
                reason_code="separately_approved_hold",
                metadata={"target_model": hold.target_model, "evidence_hash": hold.evidence_hash},
            )
        return True

    def action_release(self, *, reason):
        if not _can_govern_retention(self.env.user):
            raise AccessError(_("Only Compliance or Global Administration may release hold."))
        for hold in self:
            require_campaign_access(self.env, hold.campaign_id, roles=("compliance",))
            if hold.state != "active":
                raise ValidationError(_("Only active legal hold may be released."))
            if hold.requested_by_id == self.env.user:
                raise AccessError(_("Legal-hold requester cannot release the same hold."))
            released_at = fields.Datetime.now()
            release_hash = digest(
                {
                    "hold_evidence_hash": hold.evidence_hash,
                    "released_by_id": self.env.user.id,
                    "released_at": released_at,
                    "release_reason_hash": hash_text(reason),
                }
            )
            hold.with_context(_cc_legal_hold_capability=LEGAL_HOLD_CAPABILITY).write(
                {
                    "state": "released",
                    "released_by_id": self.env.user.id,
                    "released_at": released_at,
                    "release_evidence_hash": release_hash,
                }
            )
            self.env["cc.audit.event"]._append_event(
                event_type="cc.compliance.hold.released.v1",
                action="legal_hold_release",
                result="success",
                target_model=hold._name,
                target_record_id=hold.id,
                idempotency_key=f"legal-hold:{hold.id}:released",
                campaign=hold.campaign_id,
                reason_code="approved_hold_release",
                reason=reason,
                metadata={"release_evidence_hash": release_hash},
            )
        return True


class CcRetentionDecision(models.Model):
    _name = "cc.retention.decision"
    _description = "Immutable Retention and Legal-Hold Decision"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "evaluated_at desc, id desc"

    decision_uuid = fields.Char(required=True, readonly=True, copy=False, index=True)
    idempotency_key = fields.Char(required=True, readonly=True, copy=False, index=True)
    policy_id = fields.Many2one(
        "cc.compliance.policy", required=True, readonly=True, ondelete="restrict", index=True
    )
    target_model = fields.Selection(
        [(model_name, model_name) for model_name in RETENTION_MODEL_FIELDS],
        required=True,
        readonly=True,
        index=True,
    )
    target_reference_hash = fields.Char(required=True, readonly=True, size=64, index=True)
    record_created_at = fields.Datetime(required=True, readonly=True)
    evaluated_at = fields.Datetime(required=True, readonly=True, index=True)
    retain_until = fields.Datetime(required=True, readonly=True, index=True)
    legal_hold_id = fields.Many2one("cc.legal.hold", readonly=True, ondelete="restrict")
    outcome = fields.Selection(
        [
            ("retain", "Retain Until Policy Date"),
            ("legal_hold", "Retain Under Legal Hold"),
            ("eligible_for_review", "Eligible for Controlled Deletion Review"),
        ],
        required=True,
        readonly=True,
        index=True,
    )
    evidence_hash = fields.Char(required=True, readonly=True, size=64, index=True)

    _decision_uuid_unique = models.Constraint(
        "unique(decision_uuid)", "Retention decision UUIDs must be unique."
    )
    _idempotency_unique = models.Constraint(
        "unique(idempotency_key)", "Retention decision idempotency keys must be unique."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_retention_capability") is not RETENTION_APPEND_CAPABILITY:
            raise AccessError(_("Retention evidence requires server-side evaluation."))
        records = super().create(values_list)
        return records.with_env(
            records.env(context=dict(records.env.context, _cc_retention_capability=None))
        )

    def write(self, values):
        raise AccessError(_("Retention decisions are immutable."))

    def unlink(self):
        raise AccessError(_("Retention decisions cannot be deleted."))

    @api.model
    def assess_retention(
        self,
        *,
        policy,
        target_model,
        target_reference,
        record_created_at,
        idempotency_key,
    ):
        if not _can_govern_retention(self.env.user):
            raise AccessError(_("Only Compliance may assess controlled retention."))
        policy = self.env["cc.compliance.policy"].browse(
            getattr(policy, "id", policy)
        ).exists()
        if not policy or policy.state != "active" or target_model not in RETENTION_MODEL_FIELDS:
            raise ValidationError(_("Retention assessment requires active controlled policy."))
        campaign = require_campaign_access(self.env, policy.campaign_id, roles=("compliance",))
        target_hash = hash_text(target_reference)
        if not target_hash:
            raise ValidationError(_("Retention assessment requires a protected target reference."))
        existing = self.search([("idempotency_key", "=", idempotency_key)], limit=1)
        evaluated_at = existing.evaluated_at if existing else fields.Datetime.now()
        retention_days = getattr(policy, RETENTION_MODEL_FIELDS[target_model])
        retain_until = record_created_at + timedelta(days=retention_days)
        hold = self.env["cc.legal.hold"].search(
            [
                ("campaign_id", "=", campaign.id),
                ("target_model", "=", target_model),
                ("target_reference_hash", "=", target_hash),
                ("state", "=", "active"),
            ],
            limit=1,
        )
        outcome = "legal_hold" if hold else (
            "retain" if evaluated_at < retain_until else "eligible_for_review"
        )
        semantic = {
            "campaign_id": campaign.id,
            "policy_id": policy.id,
            "target_model": target_model,
            "target_reference_hash": target_hash,
            "record_created_at": record_created_at,
            "evaluated_at": evaluated_at,
            "retain_until": retain_until,
            "legal_hold_id": hold.id or False,
            "outcome": outcome,
        }
        evidence_hash = digest(semantic)
        if existing:
            if existing.evidence_hash != evidence_hash:
                raise ValidationError(_("Retention replay changed immutable evidence."))
            return existing
        values = {
            **semantic,
            "decision_uuid": str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"cc-retention:{idempotency_key}")
            ),
            "idempotency_key": idempotency_key,
            "evidence_hash": evidence_hash,
        }
        decision = self.with_context(
            _cc_retention_capability=RETENTION_APPEND_CAPABILITY
        ).create(values)
        self.env["cc.audit.event"]._append_event(
            event_type="cc.retention.assessed.v1",
            action="retention_assess",
            result="blocked" if outcome == "legal_hold" else "success",
            target_model=decision._name,
            target_record_id=decision.id,
            idempotency_key=f"audit:{idempotency_key}",
            campaign=campaign,
            reason_code=outcome,
            metadata={"target_model": target_model, "evidence_hash": evidence_hash},
        )
        return decision
