import hashlib
import json
import re
import uuid

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


AUDIT_APPEND_CAPABILITY = object()
BREAK_GLASS_AUDIT_CAPABILITY = object()
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
PROHIBITED_METADATA_KEYS = {
    "account_number",
    "api_key",
    "authentication",
    "bank_account",
    "card_number",
    "credential",
    "cvv",
    "email",
    "password",
    "phone",
    "pin",
    "recording_url",
    "secret",
    "security_code",
    "token",
}
SENSITIVE_VALUE_PATTERN = re.compile(
    r"(?i)(?:bearer\s+[a-z0-9._~-]+|"
    r"(?:password|passcode|api[_ -]?key|secret|cvv|cvc|security[_ -]?code)"
    r"\s*[:=]\s*\S+)"
)


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value):
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _hash_text(value):
    normalized = str(value or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else False


def _actor_role(user):
    role_groups = (
        ("global_administrator", "codestra_cc_security.group_cc_global_administrator"),
        ("compliance", "codestra_cc_security.group_cc_compliance_officer"),
        ("auditor", "codestra_cc_security.group_cc_auditor"),
        ("technical_administrator", "codestra_cc_security.group_cc_technical_administrator"),
        ("supervisor", "codestra_cc_security.group_cc_campaign_supervisor"),
        ("agent", "codestra_cc_security.group_cc_campaign_agent"),
    )
    for role, xmlid in role_groups:
        if user.has_group(xmlid):
            return role
    return "service" if not user.share else "external"


def _validate_metadata(value, path="metadata"):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if SENSITIVE_VALUE_PATTERN.search(value):
            raise ValidationError(_("Audit metadata cannot contain credentials or secrets."))
        return value
    if isinstance(value, list):
        return [_validate_metadata(item, f"{path}[]") for item in value]
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            normalized_key = str(key).strip().lower()
            if normalized_key in PROHIBITED_METADATA_KEYS or any(
                token in normalized_key
                for token in ("password", "secret", "credential", "card", "cvv")
            ):
                raise ValidationError(
                    _("Audit metadata key %(key)s is prohibited.", key=key)
                )
            clean[str(key)] = _validate_metadata(item, f"{path}.{key}")
        return clean
    raise ValidationError(_("Audit metadata must use JSON-safe values."))


class CcAuditEvent(models.Model):
    _name = "cc.audit.event"
    _description = "Append-Only Contact Center Audit Evidence"
    _order = "id desc"

    event_uuid = fields.Char(required=True, readonly=True, copy=False, index=True)
    occurred_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True, index=True
    )
    actor_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict", index=True
    )
    actor_role = fields.Char(required=True, readonly=True, index=True)
    company_id = fields.Many2one(
        "res.company", required=True, readonly=True, ondelete="restrict", index=True
    )
    campaign_id = fields.Many2one(
        "cc.campaign", readonly=True, ondelete="restrict", index=True
    )
    business_unit_id = fields.Many2one(
        "cc.business.unit",
        related="campaign_id.cc_business_unit_id",
        store=True,
        readonly=True,
        index=True,
    )
    event_type = fields.Char(required=True, readonly=True, index=True)
    action = fields.Char(required=True, readonly=True, index=True)
    result = fields.Selection(
        [
            ("success", "Success"),
            ("denied", "Denied"),
            ("blocked", "Blocked"),
            ("failure", "Failure"),
        ],
        required=True,
        readonly=True,
        index=True,
    )
    target_model = fields.Char(required=True, readonly=True, index=True)
    target_record_id = fields.Integer(readonly=True, index=True)
    reason_code = fields.Char(readonly=True, index=True)
    reason_hash = fields.Char(readonly=True, size=64)
    correlation_id = fields.Char(readonly=True, index=True)
    causation_id = fields.Char(readonly=True, index=True)
    idempotency_key = fields.Char(required=True, readonly=True, copy=False, index=True)
    source_system = fields.Char(required=True, readonly=True, default="odoo", index=True)
    source_reference_hash = fields.Char(readonly=True, size=64)
    metadata = fields.Json(readonly=True)
    payload_hash = fields.Char(required=True, readonly=True, size=64, index=True)
    previous_hash = fields.Char(required=True, readonly=True, size=64)
    record_hash = fields.Char(required=True, readonly=True, size=64, index=True)

    _event_uuid_unique = models.Constraint(
        "unique(event_uuid)", "Audit event UUIDs must be unique."
    )
    _idempotency_unique = models.Constraint(
        "unique(idempotency_key)", "Audit idempotency keys must be unique."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_audit_append_capability") is not AUDIT_APPEND_CAPABILITY:
            raise AccessError(_("Audit evidence may only be appended by governed workflows."))
        records = super().create(values_list)
        return records.with_env(
            records.env(context=dict(records.env.context, _cc_audit_append_capability=None))
        )

    def write(self, values):
        raise AccessError(_("Audit evidence is append-only."))

    def unlink(self):
        raise AccessError(_("Audit evidence cannot be deleted."))

    def copy(self, default=None):
        raise AccessError(_("Audit evidence cannot be copied."))

    def export_data(self, fields_to_export, raw_data=False):
        raise UserError(_("Raw audit export is disabled in staging."))

    @api.model
    def _append_event(
        self,
        *,
        event_type,
        action,
        result,
        target_model,
        idempotency_key,
        campaign=False,
        target_record_id=0,
        reason_code=False,
        reason=False,
        correlation_id=False,
        causation_id=False,
        source_system="odoo",
        source_reference=False,
        metadata=None,
    ):
        if result not in {"success", "denied", "blocked", "failure"}:
            raise ValidationError(_("Audit result is not controlled."))
        if not event_type or not action or not target_model or not idempotency_key:
            raise ValidationError(_("Audit events require type, action, target, and idempotency."))
        clean_metadata = _validate_metadata(metadata or {})
        campaign = self.env["cc.campaign"].browse(getattr(campaign, "id", campaign)).exists()
        semantic_payload = {
            "actor_id": self.env.user.id,
            "actor_role": _actor_role(self.env.user),
            "campaign_id": campaign.id if campaign else False,
            "event_type": event_type,
            "action": action,
            "result": result,
            "target_model": target_model,
            "target_record_id": int(target_record_id or 0),
            "reason_code": reason_code or False,
            "reason_hash": _hash_text(reason),
            "correlation_id": correlation_id or False,
            "causation_id": causation_id or False,
            "idempotency_key": idempotency_key,
            "source_system": source_system,
            "source_reference_hash": _hash_text(source_reference),
            "metadata": clean_metadata,
        }
        payload_hash = _digest(semantic_payload)
        existing = self.search([("idempotency_key", "=", idempotency_key)], limit=1)
        if existing:
            if existing.payload_hash != payload_hash:
                raise ValidationError(_("Audit replay changed immutable evidence."))
            return existing
        # Each actor has an independent hash chain. This keeps append operations
        # least-privilege: an agent or technical administrator never needs read
        # access to another actor's evidence in order to append its own event.
        previous = self.search(
            [("actor_id", "=", self.env.user.id)], order="id desc", limit=1
        )
        occurred_at = fields.Datetime.now()
        values = {
            **semantic_payload,
            "event_uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"cc-audit:{idempotency_key}")),
            "occurred_at": occurred_at,
            "company_id": (campaign.company_id or self.env.company).id,
            "payload_hash": payload_hash,
            "previous_hash": previous.record_hash or "0" * 64,
        }
        values["record_hash"] = _digest(values)
        return self.with_context(_cc_audit_append_capability=AUDIT_APPEND_CAPABILITY).create(values)

    def verify_chain(self):
        previous_by_actor = {}
        for event in self.search([], order="id asc"):
            previous_hash = previous_by_actor.get(event.actor_id.id, "0" * 64)
            if event.previous_hash != previous_hash:
                raise ValidationError(_("Contact-center audit chain continuity failed."))
            values = {
                "actor_id": event.actor_id.id,
                "actor_role": event.actor_role,
                "campaign_id": event.campaign_id.id or False,
                "event_type": event.event_type,
                "action": event.action,
                "result": event.result,
                "target_model": event.target_model,
                "target_record_id": event.target_record_id,
                "reason_code": event.reason_code or False,
                "reason_hash": event.reason_hash or False,
                "correlation_id": event.correlation_id or False,
                "causation_id": event.causation_id or False,
                "idempotency_key": event.idempotency_key,
                "source_system": event.source_system,
                "source_reference_hash": event.source_reference_hash or False,
                "metadata": event.metadata or {},
                "event_uuid": event.event_uuid,
                "occurred_at": event.occurred_at,
                "company_id": event.company_id.id,
                "payload_hash": event.payload_hash,
                "previous_hash": event.previous_hash,
            }
            if event.record_hash != _digest(values):
                raise ValidationError(_("Contact-center audit record integrity failed."))
            previous_by_actor[event.actor_id.id] = event.record_hash
        return True


class CcBreakGlassGrant(models.Model):
    _inherit = "cc.break.glass.grant"

    @api.model_create_multi
    def create(self, values_list):
        grants = super().create(values_list)
        for grant in grants:
            self.env["cc.audit.event"]._append_event(
                event_type="cc.break_glass.requested.v1",
                action="break_glass_request",
                result="success",
                target_model=grant._name,
                target_record_id=grant.id,
                idempotency_key=f"break-glass:{grant.id}:requested",
                reason_code="emergency_platform_access",
                reason=grant.reason,
                source_reference=grant.source_ticket,
                metadata={"state": grant.state, "subject_user_id": grant.user_id.id},
            )
        return grants

    def action_submit(self):
        result = super().action_submit()
        for grant in self:
            self.env["cc.audit.event"]._append_event(
                event_type="cc.break_glass.submitted.v1",
                action="break_glass_submit",
                result="success",
                target_model=grant._name,
                target_record_id=grant.id,
                idempotency_key=f"break-glass:{grant.id}:submitted",
                reason_code="separate_approval_required",
                source_reference=grant.source_ticket,
                metadata={"state": grant.state, "subject_user_id": grant.user_id.id},
            )
        return result

    def action_activate(self):
        result = super().action_activate()
        for grant in self:
            self.env["cc.audit.event"]._append_event(
                event_type="cc.break_glass.activated.v1",
                action="break_glass_activate",
                result="success",
                target_model=grant._name,
                target_record_id=grant.id,
                idempotency_key=f"break-glass:{grant.id}:activated",
                reason_code="separately_approved",
                source_reference=grant.source_ticket,
                metadata={
                    "state": grant.state,
                    "subject_user_id": grant.user_id.id,
                    "approved_by_id": grant.approved_by_id.id,
                    "ends_at": fields.Datetime.to_string(grant.ends_at),
                },
            )
        return result

    def action_revoke(self):
        states = {grant.id: grant.state for grant in self}
        result = super().action_revoke()
        for grant in self.filtered(lambda item: states[item.id] != item.state):
            self.env["cc.audit.event"]._append_event(
                event_type="cc.break_glass.revoked.v1",
                action="break_glass_revoke",
                result="success",
                target_model=grant._name,
                target_record_id=grant.id,
                idempotency_key=f"break-glass:{grant.id}:revoked",
                reason_code="access_revoked",
                source_reference=grant.source_ticket,
                metadata={
                    "state": grant.state,
                    "subject_user_id": grant.user_id.id,
                    "revoked_by_id": grant.revoked_by_id.id,
                },
            )
        return result

    def action_record_use(
        self, *, target_model, target_record_id=0, reason, idempotency_key
    ):
        self.ensure_one()
        now = fields.Datetime.now()
        if self.user_id != self.env.user:
            raise AccessError(_("Only the break-glass subject may record its use."))
        if self.state != "active" or not (self.starts_at <= now < self.ends_at):
            raise AccessError(_("Break-glass access is not active."))
        return self.env["cc.audit.event"]._append_event(
            event_type="cc.break_glass.used.v1",
            action="break_glass_use",
            result="success",
            target_model=target_model,
            target_record_id=target_record_id,
            idempotency_key=idempotency_key,
            reason_code="emergency_business_data_access",
            reason=reason,
            source_reference=self.source_ticket,
            metadata={"grant_id": self.id, "subject_user_id": self.user_id.id},
        )

    @api.model
    def action_expire_due(self):
        if not (
            self.env.user.has_group("codestra_cc_security.group_cc_global_administrator")
            or self.env.user.has_group("codestra_cc_security.group_cc_compliance_officer")
        ):
            raise AccessError(_("Only Global Administration or Compliance may expire grants."))
        now = fields.Datetime.now()
        grants = self.search([("state", "=", "active"), ("ends_at", "<=", now)])
        for grant in grants:
            grant.with_context(cc_break_glass_transition=True).write({"state": "expired"})
            grant._invalidate_security_scope()
            self.env["cc.audit.event"]._append_event(
                event_type="cc.break_glass.expired.v1",
                action="break_glass_expire",
                result="success",
                target_model=grant._name,
                target_record_id=grant.id,
                idempotency_key=f"break-glass:{grant.id}:expired",
                reason_code="approved_window_ended",
                source_reference=grant.source_ticket,
                metadata={"state": grant.state, "subject_user_id": grant.user_id.id},
            )
        return len(grants)
