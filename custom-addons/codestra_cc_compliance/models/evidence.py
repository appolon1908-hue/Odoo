import uuid
from datetime import timezone

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .policy import (
    canonical_json,
    digest,
    hash_text,
    is_compliance,
    is_compliance_service,
    is_global_admin,
    is_operational,
    require_campaign_access,
    validate_timezone,
)


CONSENT_APPEND_CAPABILITY = object()
SUPPRESSION_WRITE_CAPABILITY = object()
ELIGIBILITY_APPEND_CAPABILITY = object()


def _profile(env, value):
    profile = env["cc.customer.profile"].browse(getattr(value, "id", value)).exists()
    if not profile:
        raise ValidationError(_("A governed customer profile is required."))
    profile.check_access("read")
    return profile


def _active_policy(env, campaign, channel):
    Policy = env["cc.compliance.policy"]
    policy = Policy.search(
        [
            ("campaign_id", "=", campaign.id),
            ("state", "=", "active"),
            ("channel", "=", channel),
        ],
        limit=1,
    )
    if not policy:
        policy = Policy.search(
            [
                ("campaign_id", "=", campaign.id),
                ("state", "=", "active"),
                ("channel", "=", "all"),
            ],
            limit=1,
        )
    return policy


def _require_profile_action(env, profile):
    campaign = require_campaign_access(
        env,
        profile.campaign_id,
        roles=("agent", "senior_agent", "supervisor", "compliance"),
    )
    if is_operational(env.user):
        membership = env.user._cc_resolve_operational_membership()
        if membership.role in {"agent", "senior_agent"} and (
            profile.assigned_user_id and profile.assigned_user_id != env.user
        ):
            raise AccessError(_("Agents may record compliance only for assigned customers."))
    return campaign


class CcConsentEvidence(models.Model):
    _name = "cc.consent.evidence"
    _description = "Immutable Campaign Consent and Revocation Evidence"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "occurred_at desc, id desc"

    event_uuid = fields.Char(required=True, readonly=True, copy=False, index=True)
    idempotency_key = fields.Char(required=True, readonly=True, copy=False, index=True)
    policy_id = fields.Many2one(
        "cc.compliance.policy", required=True, readonly=True, ondelete="restrict", index=True
    )
    customer_profile_id = fields.Many2one(
        "cc.customer.profile", required=True, readonly=True, ondelete="restrict", index=True
    )
    channel = fields.Selection(
        [("phone", "Phone"), ("email", "Email"), ("sms", "SMS")],
        required=True,
        readonly=True,
        index=True,
    )
    status = fields.Selection(
        [("granted", "Granted"), ("revoked", "Revoked")],
        required=True,
        readonly=True,
        index=True,
    )
    consent_source = fields.Char(required=True, readonly=True)
    consent_text_version = fields.Char(required=True, readonly=True)
    occurred_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True, index=True
    )
    expires_at = fields.Datetime(readonly=True)
    destination_hash = fields.Char(required=True, readonly=True, size=64, index=True)
    evidence_reference_hash = fields.Char(required=True, readonly=True, size=64)
    source_payload_hash = fields.Char(required=True, readonly=True, size=64)
    previous_consent_id = fields.Many2one(
        "cc.consent.evidence", readonly=True, ondelete="restrict", index=True
    )
    actor_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict", index=True
    )
    evidence_hash = fields.Char(required=True, readonly=True, size=64, index=True)

    _event_uuid_unique = models.Constraint(
        "unique(event_uuid)", "Consent event UUIDs must be unique."
    )
    _idempotency_unique = models.Constraint(
        "unique(idempotency_key)", "Consent idempotency keys must be unique."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_consent_append_capability") is not CONSENT_APPEND_CAPABILITY:
            raise AccessError(_("Consent evidence requires the governed capture workflow."))
        records = super().create(values_list)
        return records.with_env(
            records.env(context=dict(records.env.context, _cc_consent_append_capability=None))
        )

    def write(self, values):
        raise AccessError(_("Consent and revocation evidence is immutable."))

    def unlink(self):
        raise AccessError(_("Consent and revocation evidence cannot be deleted."))

    @api.model
    def record_consent(
        self,
        *,
        customer_profile,
        channel,
        destination,
        consent_source,
        consent_text_version,
        evidence_reference,
        source_payload_hash,
        idempotency_key,
        expires_at=False,
    ):
        profile = _profile(self.env, customer_profile)
        campaign = _require_profile_action(self.env, profile)
        policy = _active_policy(self.env, campaign, channel)
        if not policy:
            raise ValidationError(_("An active campaign compliance policy is required."))
        if consent_text_version != policy.consent_text_version:
            raise ValidationError(_("Consent text version must match active policy."))
        if not destination or not evidence_reference or len(str(source_payload_hash)) != 64:
            raise ValidationError(_("Consent requires destination, protected evidence, and source hash."))
        existing = self.search([("idempotency_key", "=", idempotency_key)], limit=1)
        occurred_at = existing.occurred_at if existing else fields.Datetime.now()
        values = {
            "campaign_id": campaign.id,
            "event_uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"cc-consent:{idempotency_key}")),
            "idempotency_key": idempotency_key,
            "policy_id": policy.id,
            "customer_profile_id": profile.id,
            "channel": channel,
            "status": "granted",
            "consent_source": consent_source,
            "consent_text_version": consent_text_version,
            "occurred_at": occurred_at,
            "expires_at": expires_at or False,
            "destination_hash": hash_text(destination),
            "evidence_reference_hash": hash_text(evidence_reference),
            "source_payload_hash": str(source_payload_hash).lower(),
            "actor_id": self.env.user.id,
        }
        values["evidence_hash"] = digest(values)
        if existing:
            if existing.evidence_hash != values["evidence_hash"]:
                raise ValidationError(_("Consent replay changed immutable evidence."))
            return existing
        record = self.with_context(_cc_consent_append_capability=CONSENT_APPEND_CAPABILITY).create(values)
        self.env["cc.audit.event"]._append_event(
            event_type="cc.consent.recorded.v1",
            action="consent_record",
            result="success",
            target_model=record._name,
            target_record_id=record.id,
            idempotency_key=f"audit:{idempotency_key}",
            campaign=campaign,
            reason_code="consent_captured",
            metadata={
                "channel": channel,
                "text_version": consent_text_version,
                "evidence_hash": record.evidence_hash,
            },
        )
        return record

    def record_revocation(
        self,
        *,
        consent,
        destination,
        source,
        evidence_reference,
        source_payload_hash,
        idempotency_key,
    ):
        consent = self.browse(getattr(consent, "id", consent)).exists()
        if not consent or consent.status != "granted":
            raise ValidationError(_("Revocation must reference granted consent."))
        profile = _profile(self.env, consent.customer_profile_id)
        campaign = _require_profile_action(self.env, profile)
        destination_hash = hash_text(destination)
        if destination_hash != consent.destination_hash:
            raise ValidationError(_("Revocation destination must match granted consent."))
        existing = self.search([("idempotency_key", "=", idempotency_key)], limit=1)
        occurred_at = existing.occurred_at if existing else fields.Datetime.now()
        values = {
            "campaign_id": campaign.id,
            "event_uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"cc-consent:{idempotency_key}")),
            "idempotency_key": idempotency_key,
            "policy_id": consent.policy_id.id,
            "customer_profile_id": profile.id,
            "channel": consent.channel,
            "status": "revoked",
            "consent_source": source,
            "consent_text_version": consent.consent_text_version,
            "occurred_at": occurred_at,
            "destination_hash": destination_hash,
            "evidence_reference_hash": hash_text(evidence_reference),
            "source_payload_hash": str(source_payload_hash).lower(),
            "previous_consent_id": consent.id,
            "actor_id": self.env.user.id,
        }
        values["evidence_hash"] = digest(values)
        if existing:
            if existing.evidence_hash != values["evidence_hash"]:
                raise ValidationError(_("Consent-revocation replay changed evidence."))
            return existing
        revocation = self.with_context(
            _cc_consent_append_capability=CONSENT_APPEND_CAPABILITY
        ).create(values)
        self.env["cc.suppression.entry"].record_suppression(
            customer_profile=profile,
            identifier_type=consent.channel,
            identifier=destination,
            reason="consent_revocation",
            source_reference=evidence_reference,
            idempotency_key=f"suppression:{idempotency_key}",
        )
        self.env["cc.audit.event"]._append_event(
            event_type="cc.consent.revoked.v1",
            action="consent_revoke",
            result="success",
            target_model=revocation._name,
            target_record_id=revocation.id,
            idempotency_key=f"audit:{idempotency_key}",
            campaign=campaign,
            reason_code="customer_revocation",
            metadata={"channel": consent.channel, "evidence_hash": revocation.evidence_hash},
        )
        return revocation


class CcSuppressionEntry(models.Model):
    _name = "cc.suppression.entry"
    _description = "Governed DNC and Contact Suppression"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "recorded_at desc, id desc"

    suppression_uuid = fields.Char(required=True, readonly=True, copy=False, index=True)
    idempotency_key = fields.Char(required=True, readonly=True, copy=False, index=True)
    customer_profile_id = fields.Many2one(
        "cc.customer.profile", required=True, readonly=True, ondelete="restrict", index=True
    )
    identifier_type = fields.Selection(
        [("phone", "Phone"), ("email", "Email"), ("sms", "SMS")],
        required=True,
        readonly=True,
        index=True,
    )
    identifier_hash = fields.Char(required=True, readonly=True, size=64, index=True)
    reason = fields.Selection(
        [
            ("dnc", "Do Not Call"),
            ("unsubscribe", "Unsubscribe"),
            ("consent_revocation", "Consent Revocation"),
            ("complaint", "Complaint"),
            ("legal", "Legal / Regulatory"),
            ("risk", "Fraud / Risk"),
        ],
        required=True,
        readonly=True,
        index=True,
    )
    state = fields.Selection(
        [
            ("active", "Active"),
            ("release_pending", "Release Pending"),
            ("released", "Released"),
        ],
        required=True,
        default="active",
        readonly=True,
        index=True,
    )
    source_reference_hash = fields.Char(required=True, readonly=True, size=64)
    recorded_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True, index=True
    )
    recorded_by_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict"
    )
    release_requested_by_id = fields.Many2one("res.users", readonly=True, ondelete="restrict")
    release_requested_at = fields.Datetime(readonly=True)
    release_reason_hash = fields.Char(readonly=True, size=64)
    release_ticket_hash = fields.Char(readonly=True, size=64)
    release_approved_by_id = fields.Many2one("res.users", readonly=True, ondelete="restrict")
    released_at = fields.Datetime(readonly=True)
    evidence_hash = fields.Char(required=True, readonly=True, size=64, index=True)
    release_evidence_hash = fields.Char(readonly=True, size=64, index=True)

    _suppression_uuid_unique = models.Constraint(
        "unique(suppression_uuid)", "Suppression UUIDs must be unique."
    )
    _idempotency_unique = models.Constraint(
        "unique(idempotency_key)", "Suppression idempotency keys must be unique."
    )
    _one_active_identifier = models.UniqueIndex(
        "(campaign_id, identifier_type, identifier_hash) WHERE state IN ('active', 'release_pending')",
        "A destination may have only one active campaign suppression.",
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_suppression_capability") is not SUPPRESSION_WRITE_CAPABILITY:
            raise AccessError(_("Suppression requires the governed DNC workflow."))
        records = super().create(values_list)
        return records.with_env(
            records.env(context=dict(records.env.context, _cc_suppression_capability=None))
        )

    def write(self, values):
        if self.env.context.get("_cc_suppression_capability") is not SUPPRESSION_WRITE_CAPABILITY:
            raise AccessError(_("Suppression changes require separate governed approval."))
        return super().write(values)

    def unlink(self):
        raise AccessError(_("Suppression evidence cannot be deleted."))

    @api.model
    def record_suppression(
        self,
        *,
        customer_profile,
        identifier_type,
        identifier,
        reason,
        source_reference,
        idempotency_key,
    ):
        profile = _profile(self.env, customer_profile)
        campaign = _require_profile_action(self.env, profile)
        if identifier_type not in {"phone", "email", "sms"} or reason not in {
            "dnc", "unsubscribe", "consent_revocation", "complaint", "legal", "risk"
        }:
            raise ValidationError(_("Suppression type or reason is not controlled."))
        identifier_hash = hash_text(identifier)
        if not identifier_hash or not source_reference:
            raise ValidationError(_("Suppression requires an identifier and protected source."))
        existing = self.search([("idempotency_key", "=", idempotency_key)], limit=1)
        semantic = {
            "campaign_id": campaign.id,
            "customer_profile_id": profile.id,
            "identifier_type": identifier_type,
            "identifier_hash": identifier_hash,
            "reason": reason,
            "source_reference_hash": hash_text(source_reference),
            "recorded_by_id": self.env.user.id,
        }
        evidence_hash = digest(semantic)
        if existing:
            if existing.evidence_hash != evidence_hash:
                raise ValidationError(_("Suppression replay changed immutable evidence."))
            return existing
        active = self.search(
            [
                ("campaign_id", "=", campaign.id),
                ("identifier_type", "=", identifier_type),
                ("identifier_hash", "=", identifier_hash),
                ("state", "in", ("active", "release_pending")),
            ],
            limit=1,
        )
        if active:
            return active
        values = {
            **semantic,
            "suppression_uuid": str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"cc-suppression:{idempotency_key}")
            ),
            "idempotency_key": idempotency_key,
            "state": "active",
            "recorded_at": fields.Datetime.now(),
            "evidence_hash": evidence_hash,
        }
        entry = self.with_context(_cc_suppression_capability=SUPPRESSION_WRITE_CAPABILITY).create(
            values
        )
        self.env["cc.audit.event"]._append_event(
            event_type="cc.dnc.recorded.v1",
            action="suppression_record",
            result="success",
            target_model=entry._name,
            target_record_id=entry.id,
            idempotency_key=f"audit:{idempotency_key}",
            campaign=campaign,
            reason_code=reason,
            source_reference=source_reference,
            metadata={"identifier_type": identifier_type, "evidence_hash": entry.evidence_hash},
        )
        return entry

    def action_request_release(self, *, reason, source_ticket):
        if not (is_compliance(self.env.user) or is_global_admin(self.env.user)):
            raise AccessError(_("Only Compliance or Global Administration may request removal."))
        for entry in self:
            require_campaign_access(self.env, entry.campaign_id, roles=("compliance",))
            if entry.state != "active":
                raise ValidationError(_("Only active suppression may enter removal review."))
            values = {
                "state": "release_pending",
                "release_requested_by_id": self.env.user.id,
                "release_requested_at": fields.Datetime.now(),
                "release_reason_hash": hash_text(reason),
                "release_ticket_hash": hash_text(source_ticket),
            }
            entry.with_context(_cc_suppression_capability=SUPPRESSION_WRITE_CAPABILITY).write(values)
        return True

    def action_approve_release(self):
        if not (is_compliance(self.env.user) or is_global_admin(self.env.user)):
            raise AccessError(_("Only Compliance or Global Administration may approve removal."))
        for entry in self:
            require_campaign_access(self.env, entry.campaign_id, roles=("compliance",))
            if entry.state != "release_pending":
                raise ValidationError(_("Suppression removal is not pending."))
            if entry.release_requested_by_id == self.env.user:
                raise AccessError(_("Suppression removal requester cannot approve it."))
            released_at = fields.Datetime.now()
            release_hash = digest(
                {
                    "suppression": entry.evidence_hash,
                    "requested_by": entry.release_requested_by_id.id,
                    "approved_by": self.env.user.id,
                    "released_at": released_at,
                    "reason_hash": entry.release_reason_hash,
                    "ticket_hash": entry.release_ticket_hash,
                }
            )
            entry.with_context(_cc_suppression_capability=SUPPRESSION_WRITE_CAPABILITY).write(
                {
                    "state": "released",
                    "release_approved_by_id": self.env.user.id,
                    "released_at": released_at,
                    "release_evidence_hash": release_hash,
                }
            )
            self.env["cc.audit.event"]._append_event(
                event_type="cc.suppression.released.v1",
                action="suppression_release",
                result="success",
                target_model=entry._name,
                target_record_id=entry.id,
                idempotency_key=f"suppression:{entry.id}:released",
                campaign=entry.campaign_id,
                reason_code="separately_approved_removal",
                metadata={"release_evidence_hash": release_hash},
            )
        return True


class CcContactEligibilityEvidence(models.Model):
    _name = "cc.contact.eligibility.evidence"
    _description = "Immutable Pre-Dial Compliance Decision"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "evaluated_at desc, id desc"

    request_uuid = fields.Char(required=True, readonly=True, copy=False, index=True)
    idempotency_key = fields.Char(required=True, readonly=True, copy=False, index=True)
    policy_id = fields.Many2one("cc.compliance.policy", readonly=True, ondelete="restrict")
    customer_profile_id = fields.Many2one(
        "cc.customer.profile", required=True, readonly=True, ondelete="restrict", index=True
    )
    channel = fields.Selection(
        [("phone", "Phone"), ("email", "Email"), ("sms", "SMS")],
        required=True,
        readonly=True,
        index=True,
    )
    dial_mode = fields.Selection(
        [("manual", "Manual"), ("automated", "Automated"), ("predictive", "Predictive")],
        required=True,
        readonly=True,
    )
    voice_mode = fields.Selection(
        [("human", "Human"), ("ai", "AI Voice"), ("prerecorded", "Prerecorded")],
        required=True,
        readonly=True,
    )
    evaluated_at = fields.Datetime(required=True, readonly=True, index=True)
    customer_timezone = fields.Char(required=True, readonly=True)
    customer_local_weekday = fields.Integer(required=True, readonly=True)
    customer_local_minute = fields.Integer(required=True, readonly=True)
    destination_hash = fields.Char(required=True, readonly=True, size=64, index=True)
    result = fields.Selection(
        [
            ("eligible", "Eligible"),
            ("blocked_dnc", "Blocked: DNC / Suppression"),
            ("blocked_consent", "Blocked: Consent"),
            ("outside_hours", "Blocked: Calling Hours"),
            ("blocked_capability", "Blocked: Capability"),
            ("blocked_policy", "Blocked: Missing Policy"),
        ],
        required=True,
        readonly=True,
        index=True,
    )
    reason_codes = fields.Json(readonly=True)
    consent_evidence_id = fields.Many2one("cc.consent.evidence", readonly=True, ondelete="restrict")
    suppression_entry_id = fields.Many2one("cc.suppression.entry", readonly=True, ondelete="restrict")
    actor_id = fields.Many2one("res.users", required=True, readonly=True, ondelete="restrict")
    evidence_hash = fields.Char(required=True, readonly=True, size=64, index=True)

    _request_uuid_unique = models.Constraint(
        "unique(request_uuid)", "Eligibility request UUIDs must be unique."
    )
    _idempotency_unique = models.Constraint(
        "unique(idempotency_key)", "Eligibility idempotency keys must be unique."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_eligibility_capability") is not ELIGIBILITY_APPEND_CAPABILITY:
            raise AccessError(_("Eligibility evidence requires server-side evaluation."))
        records = super().create(values_list)
        return records.with_env(
            records.env(context=dict(records.env.context, _cc_eligibility_capability=None))
        )

    def write(self, values):
        raise AccessError(_("Eligibility evidence is immutable."))

    def unlink(self):
        raise AccessError(_("Eligibility evidence cannot be deleted."))

    @api.model
    def evaluate_contact(
        self,
        *,
        customer_profile,
        channel,
        destination,
        idempotency_key,
        dial_mode="manual",
        voice_mode="human",
    ):
        return self._evaluate_at(
            customer_profile=customer_profile,
            channel=channel,
            destination=destination,
            idempotency_key=idempotency_key,
            dial_mode=dial_mode,
            voice_mode=voice_mode,
            evaluated_at=fields.Datetime.now(),
        )

    @api.model
    def _evaluate_at(
        self,
        *,
        customer_profile,
        channel,
        destination,
        idempotency_key,
        dial_mode,
        voice_mode,
        evaluated_at,
    ):
        existing = self.search([("idempotency_key", "=", idempotency_key)], limit=1)
        if existing:
            evaluated_at = existing.evaluated_at
        profile = _profile(self.env, customer_profile)
        campaign = _require_profile_action(self.env, profile)
        if channel not in {"phone", "email", "sms"}:
            raise ValidationError(_("Compliance channel is not controlled."))
        if dial_mode not in {"manual", "automated", "predictive"} or voice_mode not in {
            "human", "ai", "prerecorded"
        }:
            raise ValidationError(_("Contact capability mode is not controlled."))
        destination_hash = hash_text(destination)
        if not destination_hash:
            raise ValidationError(_("A destination is required for eligibility evaluation."))
        tz = validate_timezone(profile.contact_timezone)
        aware_utc = evaluated_at.replace(tzinfo=timezone.utc)
        local = aware_utc.astimezone(tz)
        local_minute = local.hour * 60 + local.minute
        policy = _active_policy(self.env, campaign, channel)
        reasons = []
        result = "eligible"
        suppression = self.env["cc.suppression.entry"].search(
            [
                ("campaign_id", "=", campaign.id),
                ("identifier_type", "=", channel),
                ("identifier_hash", "=", destination_hash),
                ("state", "in", ("active", "release_pending")),
            ],
            limit=1,
        )
        consent = self.env["cc.consent.evidence"].search(
            [
                ("campaign_id", "=", campaign.id),
                ("customer_profile_id", "=", profile.id),
                ("channel", "=", channel),
                ("destination_hash", "=", destination_hash),
            ],
            order="occurred_at desc, id desc",
            limit=1,
        )
        if suppression:
            result = "blocked_dnc"
            reasons.append(suppression.reason)
        elif not policy:
            result = "blocked_policy"
            reasons.append("active_policy_missing")
        elif policy.consent_required and (
            not consent
            or consent.status != "granted"
            or (consent.expires_at and consent.expires_at <= evaluated_at)
        ):
            result = "blocked_consent"
            reasons.append("valid_consent_missing")
        elif dial_mode == "automated" and not policy.automated_outreach_allowed:
            result = "blocked_capability"
            reasons.append("automated_outreach_disabled")
        elif dial_mode == "predictive" and not policy.predictive_dialing_allowed:
            result = "blocked_capability"
            reasons.append("predictive_dialing_disabled")
        elif voice_mode == "ai" and not policy.ai_voice_allowed:
            result = "blocked_capability"
            reasons.append("ai_voice_disabled")
        elif voice_mode == "prerecorded" and not policy.prerecorded_voice_allowed:
            result = "blocked_capability"
            reasons.append("prerecorded_voice_disabled")
        elif local.weekday() not in (policy.allowed_weekdays or []):
            result = "outside_hours"
            reasons.append("weekday_not_allowed")
        elif not (
            int(policy.calling_hour_start * 60)
            <= local_minute
            < int(policy.calling_hour_end * 60)
        ):
            result = "outside_hours"
            reasons.append("customer_local_time_outside_window")
        semantic = {
            "campaign_id": campaign.id,
            "policy_id": policy.id if policy else False,
            "customer_profile_id": profile.id,
            "channel": channel,
            "dial_mode": dial_mode,
            "voice_mode": voice_mode,
            "evaluated_at": evaluated_at,
            "customer_timezone": profile.contact_timezone,
            "customer_local_weekday": local.weekday(),
            "customer_local_minute": local_minute,
            "destination_hash": destination_hash,
            "result": result,
            "reason_codes": reasons,
            "consent_evidence_id": consent.id or False,
            "suppression_entry_id": suppression.id or False,
            "actor_id": self.env.user.id,
        }
        evidence_hash = digest(semantic)
        if existing:
            if existing.evidence_hash != evidence_hash:
                raise ValidationError(_("Eligibility replay changed immutable evidence."))
            return existing
        values = {
            **semantic,
            "request_uuid": str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"cc-eligibility:{idempotency_key}")
            ),
            "idempotency_key": idempotency_key,
            "evidence_hash": evidence_hash,
        }
        evidence = self.with_context(
            _cc_eligibility_capability=ELIGIBILITY_APPEND_CAPABILITY
        ).create(values)
        self.env["cc.audit.event"]._append_event(
            event_type="cc.contact.eligibility.evaluated.v1",
            action="contact_eligibility_evaluate",
            result="success" if result == "eligible" else "blocked",
            target_model=evidence._name,
            target_record_id=evidence.id,
            idempotency_key=f"audit:{idempotency_key}",
            campaign=campaign,
            reason_code=result,
            metadata={"channel": channel, "reason_codes": reasons, "evidence_hash": evidence_hash},
        )
        return evidence

    @api.model
    def assert_contact_allowed(self, **values):
        evidence = self.evaluate_contact(**values)
        if evidence.result != "eligible":
            raise UserError(
                _(
                    "Contact is blocked by %(result)s (%(reasons)s).",
                    result=evidence.result,
                    reasons=", ".join(evidence.reason_codes or []),
                )
            )
        return evidence


class CrmLead(models.Model):
    _inherit = "crm.lead"

    def _cc_assert_contact_allowed(self):
        self.ensure_one()
        if not self.campaign_id:
            return self.env["cc.contact.eligibility.evidence"]
        if not self.cc_customer_profile_id:
            raise UserError(_("Campaign calls require a governed customer profile."))
        destination = self.x_phone_e164 or self.phone or self.mobile
        return self.env["cc.contact.eligibility.evidence"].assert_contact_allowed(
            customer_profile=self.cc_customer_profile_id,
            channel="phone",
            destination=destination,
            idempotency_key=str(uuid.uuid4()),
            dial_mode="manual",
            voice_mode="human",
        )

    def action_click_to_call(self):
        self.ensure_one()
        self._cc_assert_contact_allowed()
        return super().action_click_to_call()
