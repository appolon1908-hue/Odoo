import hashlib
import uuid

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .callback import (
    _active_membership,
    _canonical_json,
    _digest,
    _is_operational,
    _is_service,
    _resolve_campaign,
)


TRANSFER_WRITE_CAPABILITY = object()
TRANSFER_EVENT_CAPABILITY = object()
REFERRAL_WRITE_CAPABILITY = object()
REFERRAL_DELIVERY_CAPABILITY = object()

SAFE_REFERRAL_KEYS = {
    "customer_name",
    "email_masked",
    "language",
    "phone_masked",
    "preferred_contact_window",
    "request_summary",
}
FORBIDDEN_KEYS = {
    "account_number",
    "api_key",
    "bank_account",
    "card_number",
    "cvv",
    "password",
    "pin",
    "secret",
    "security_code",
    "token",
}


class CcTransferRoute(models.Model):
    _name = "cc.transfer.route"
    _description = "Same-Campaign Transfer Route"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "campaign_id, name"

    name = fields.Char(required=True)
    route_code = fields.Char(required=True, index=True)
    destination_type = fields.Selection(
        [
            ("queue", "Campaign Queue"),
            ("agent", "Campaign Agent"),
            ("closer", "Campaign Closer"),
            ("support", "Campaign Support"),
            ("supervisor", "Campaign Supervisor"),
        ],
        required=True,
    )
    destination_code = fields.Char(required=True)
    destination_membership_id = fields.Many2one(
        "cc.campaign.membership", ondelete="restrict"
    )
    transfer_type = fields.Selection(
        [("blind", "Blind"), ("warm", "Warm")], required=True, default="warm"
    )
    active = fields.Boolean(default=False, required=True)
    live_control_enabled = fields.Boolean(default=False, required=True, readonly=True)

    _route_code_unique = models.Constraint(
        "unique(campaign_id, route_code)",
        "Transfer route codes must be unique in a campaign.",
    )

    @api.model_create_multi
    def create(self, values_list):
        prepared = []
        for original in values_list:
            values = dict(original)
            values["route_code"] = str(values.get("route_code") or "").strip().upper()
            prepared.append(values)
        records = super().create(prepared)
        records._check_route()
        return records

    def write(self, values):
        if "route_code" in values:
            values = dict(values, route_code=str(values["route_code"] or "").strip().upper())
        result = super().write(values)
        self._check_route()
        return result

    @api.constrains(
        "campaign_id", "destination_membership_id", "destination_type", "live_control_enabled"
    )
    def _check_route(self):
        for route in self:
            if route.destination_membership_id and (
                route.destination_membership_id.campaign_id != route.campaign_id
                or route.destination_membership_id.state != "active"
            ):
                raise ValidationError(_("Transfer destinations must remain in the source campaign."))
            if route.destination_type == "agent" and not route.destination_membership_id:
                raise ValidationError(_("Agent transfer routes require a same-campaign member."))
            if route.live_control_enabled:
                raise ValidationError(_("CC_ENABLE_WARM_TRANSFER remains false in staging."))


class CcTransfer(models.Model):
    _name = "cc.transfer"
    _description = "Validated Campaign Transfer"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "requested_at desc, id desc"

    operation_uuid = fields.Char(
        string="Transfer UUID", required=True, default=lambda self: str(uuid.uuid4()),
        readonly=True, copy=False, index=True,
    )
    source_call_unique_id = fields.Char(required=True, readonly=True, index=True)
    customer_profile_id = fields.Many2one(
        "cc.customer.profile", required=True, readonly=True, ondelete="restrict", index=True
    )
    script_version_id = fields.Many2one(
        "cc.script.version", required=True, readonly=True, ondelete="restrict"
    )
    source_membership_id = fields.Many2one(
        "cc.campaign.membership", required=True, readonly=True, ondelete="restrict"
    )
    route_id = fields.Many2one(
        "cc.transfer.route", required=True, readonly=True, ondelete="restrict"
    )
    destination_membership_id = fields.Many2one(
        related="route_id.destination_membership_id", store=True, readonly=True
    )
    requested_target_campaign_id = fields.Many2one(
        "cc.campaign",
        readonly=True,
        ondelete="restrict",
        groups=(
            "codestra_cc_calls.group_cc_call_service,"
            "codestra_cc_security.group_cc_campaign_configuration_manager,"
            "codestra_cc_security.group_cc_global_administrator"
        ),
    )
    transfer_type = fields.Selection(
        [("blind", "Blind"), ("warm", "Warm")], required=True, readonly=True
    )
    compliance_state = fields.Selection(
        [("allowed", "Allowed"), ("blocked", "Blocked"), ("unknown", "Unknown")],
        required=True,
        readonly=True,
    )
    state = fields.Selection(
        [
            ("validated", "Validated"),
            ("rejected", "Rejected"),
            ("completed", "Completed"),
            ("failed", "Failed"),
        ],
        required=True,
        readonly=True,
        index=True,
    )
    safe_status = fields.Char(required=True, readonly=True)
    rejection_code = fields.Selection(
        [
            ("cross_campaign", "Cross-Campaign Destination"),
            ("compliance_blocked", "Compliance Blocked"),
            ("invalid_route", "Invalid Route"),
            ("invalid_context", "Invalid Context"),
        ],
        readonly=True,
        index=True,
    )
    requested_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    completed_at = fields.Datetime(readonly=True)
    idempotency_key = fields.Char(required=True, readonly=True, copy=False, index=True)
    correlation_id = fields.Char(required=True, readonly=True, copy=False, index=True)
    event_ids = fields.One2many("cc.transfer.event", "transfer_id", readonly=True)

    _operation_uuid_unique = models.Constraint(
        "unique(operation_uuid)", "Transfer UUIDs must be unique."
    )
    _transfer_idempotency_unique = models.Constraint(
        "unique(idempotency_key)", "Transfer idempotency keys must be unique."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_transfer_write_capability") is not TRANSFER_WRITE_CAPABILITY:
            raise AccessError(_("Transfers require the governed validation service."))
        records = super().create(values_list)
        records._check_transfer_scope()
        return records.with_env(records.env(context=dict(records.env.context, _cc_transfer_write_capability=None)))

    def write(self, values):
        if self.env.context.get("_cc_transfer_write_capability") is not TRANSFER_WRITE_CAPABILITY:
            raise AccessError(_("Transfer evidence requires a governed lifecycle action."))
        result = super().write(values)
        self._check_transfer_scope()
        return result

    def unlink(self):
        raise AccessError(_("Transfer evidence cannot be deleted."))

    def copy(self, default=None):
        raise AccessError(_("Transfers cannot be copied."))

    def export_data(self, fields_to_export, raw_data=False):
        if _is_operational(self.env.user):
            raise UserError(_("Operational transfer export is disabled."))
        return super().export_data(fields_to_export, raw_data=raw_data)

    @api.constrains(
        "campaign_id", "customer_profile_id", "script_version_id", "source_membership_id",
        "route_id", "requested_target_campaign_id", "state",
    )
    def _check_transfer_scope(self):
        for transfer in self:
            if transfer.customer_profile_id.campaign_id != transfer.campaign_id:
                raise ValidationError(_("Transfer and customer profile campaigns differ."))
            if transfer.script_version_id.script_id.campaign_id != transfer.campaign_id:
                raise ValidationError(_("Transfer script belongs to another campaign."))
            if transfer.source_membership_id.campaign_id != transfer.campaign_id:
                raise ValidationError(_("Transfer source member belongs to another campaign."))
            if transfer.route_id.campaign_id != transfer.campaign_id:
                raise ValidationError(_("Transfer route belongs to another campaign."))
            target_differs = False
            if (
                _is_service(self.env.user)
                or self.env.user.has_group(
                    "codestra_cc_security.group_cc_campaign_configuration_manager"
                )
                or self.env.user.has_group(
                    "codestra_cc_security.group_cc_global_administrator"
                )
            ):
                target_differs = transfer.requested_target_campaign_id and (
                    transfer.requested_target_campaign_id != transfer.campaign_id
                )
            if target_differs and transfer.state != "rejected":
                raise ValidationError(_("Cross-campaign live transfers must be rejected."))

    @api.model
    def request_transfer(
        self,
        *,
        campaign_id,
        source_call_unique_id,
        customer_profile_id,
        script_version_id,
        route_id,
        compliance_state,
        idempotency_key,
        correlation_id,
        requested_target_campaign_id=False,
    ):
        campaign = _resolve_campaign(self.env, campaign_id)
        membership = _active_membership(
            self.env, campaign, allowed_roles={"agent", "senior_agent", "supervisor"}
        )
        profile = self.env["cc.customer.profile"].browse(customer_profile_id).exists()
        script = self.env["cc.script.version"].browse(script_version_id).exists()
        route = self.env["cc.transfer.route"].browse(route_id).exists()
        if not profile or not script or not route:
            raise ValidationError(_("Transfer context is incomplete."))
        profile.check_access("read")
        script.check_access("read")
        route.check_access("read")
        existing = self.search([("idempotency_key", "=", idempotency_key)], limit=1)
        if existing:
            expected = {
                "campaign": campaign.id,
                "profile": profile.id,
                "script": script.id,
                "route": route.id,
                "call": source_call_unique_id,
            }
            actual = {
                "campaign": existing.campaign_id.id,
                "profile": existing.customer_profile_id.id,
                "script": existing.script_version_id.id,
                "route": existing.route_id.id,
                "call": existing.source_call_unique_id,
            }
            if expected != actual:
                raise ValidationError(_("Transfer idempotency binding conflict."))
            return existing
        target = self.env["cc.campaign"].browse(requested_target_campaign_id).exists()
        rejection = False
        if target and target != campaign:
            rejection = "cross_campaign"
        elif profile.campaign_id != campaign or script.script_id.campaign_id != campaign:
            rejection = "invalid_context"
        elif route.campaign_id != campaign or not route.active:
            rejection = "invalid_route"
        elif compliance_state != "allowed":
            rejection = "compliance_blocked"
        values = {
            "campaign_id": campaign.id,
            "source_call_unique_id": source_call_unique_id,
            "customer_profile_id": profile.id,
            "script_version_id": script.id,
            "source_membership_id": membership.id,
            "route_id": route.id,
            "transfer_type": route.transfer_type,
            "compliance_state": compliance_state,
            "state": "rejected" if rejection else "validated",
            "safe_status": (
                "Transfer unavailable for this call." if rejection else "Same-campaign transfer validated."
            ),
            "rejection_code": rejection,
            "idempotency_key": idempotency_key,
            "correlation_id": correlation_id,
        }
        if target and (
            _is_service(self.env.user)
            or self.env.user.has_group("codestra_cc_security.group_cc_global_administrator")
        ):
            values["requested_target_campaign_id"] = target.id
        transfer = self.with_context(_cc_transfer_write_capability=TRANSFER_WRITE_CAPABILITY).create(values)
        event_type = "rejected" if rejection else "validated"
        self.env["cc.transfer.event"]._append(transfer, f"cc.transfer.{event_type}.v1", idempotency_key)
        if not rejection:
            payload = {
                "transfer_uuid": transfer.operation_uuid,
                "campaign_code": campaign.code,
                "source_call_unique_id": source_call_unique_id,
                "route_code": route.route_code,
                "transfer_type": route.transfer_type,
                "compliance_state": compliance_state,
            }
            self.env["cc.operation.outbox"]._emit(
                transfer,
                "cc.transfer.validated.v1",
                idempotency_key,
                correlation_id,
                payload,
                "warm_transfer_disabled",
            )
        return transfer

    def action_live_transfer(self):
        raise UserError(_("CC_ENABLE_WARM_TRANSFER is false; live transfer control is blocked."))

    def action_record_result(self, event_id, result):
        if not _is_service(self.env.user):
            raise AccessError(_("Only the call integration service may record transfer results."))
        if result not in {"completed", "failed"}:
            raise ValidationError(_("Transfer result must be completed or failed."))
        for transfer in self:
            existing = transfer.event_ids.filtered(lambda row: row.event_id == event_id)
            if existing:
                if existing.event_type != f"cc.transfer.{result}.v1":
                    raise ValidationError(_("Transfer result event binding conflict."))
                continue
            transfer.with_context(_cc_transfer_write_capability=TRANSFER_WRITE_CAPABILITY).write(
                {"state": result, "safe_status": f"Transfer {result}.", "completed_at": fields.Datetime.now()}
            )
            self.env["cc.transfer.event"]._append(
                transfer, f"cc.transfer.{result}.v1", event_id
            )
        return True


class CcTransferEvent(models.Model):
    _name = "cc.transfer.event"
    _description = "Immutable Transfer Event"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "occurred_at desc, id desc"

    transfer_id = fields.Many2one("cc.transfer", required=True, ondelete="restrict", index=True)
    event_id = fields.Char(required=True, readonly=True, copy=False, index=True)
    event_type = fields.Char(required=True, readonly=True, index=True)
    actor_id = fields.Many2one("res.users", required=True, readonly=True, ondelete="restrict")
    occurred_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)

    _transfer_event_unique = models.Constraint(
        "unique(transfer_id, event_id)", "Transfer events must be exactly once."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_transfer_event_capability") is not TRANSFER_EVENT_CAPABILITY:
            raise AccessError(_("Transfer events require the governed lifecycle."))
        records = super().create(values_list)
        return records.with_env(records.env(context=dict(records.env.context, _cc_transfer_event_capability=None)))

    def write(self, values):
        raise AccessError(_("Transfer events are append-only."))

    def unlink(self):
        raise AccessError(_("Transfer events cannot be deleted."))

    @api.model
    def _append(self, transfer, event_type, event_id):
        existing = self.search([("transfer_id", "=", transfer.id), ("event_id", "=", event_id)], limit=1)
        if existing:
            return existing
        return self.with_context(_cc_transfer_event_capability=TRANSFER_EVENT_CAPABILITY).create(
            {
                "campaign_id": transfer.campaign_id.id,
                "transfer_id": transfer.id,
                "event_id": event_id,
                "event_type": event_type,
                "actor_id": self.env.user.id,
            }
        )


class CcReferralRoute(models.Model):
    _name = "cc.referral.route"
    _description = "Controlled Cross-Campaign Referral Route"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "campaign_id, service_label"

    service_code = fields.Char(required=True, index=True)
    service_label = fields.Char(required=True)
    destination_campaign_id = fields.Many2one(
        "cc.campaign",
        required=True,
        ondelete="restrict",
        groups=(
            "codestra_cc_calls.group_cc_call_service,"
            "codestra_cc_security.group_cc_campaign_configuration_manager,"
            "codestra_cc_security.group_cc_global_administrator"
        ),
    )
    allowed_payload_keys = fields.Json(default=lambda self: sorted(SAFE_REFERRAL_KEYS))
    consent_required = fields.Boolean(default=True, required=True, readonly=True)
    active = fields.Boolean(default=False, required=True)
    delivery_enabled = fields.Boolean(default=False, required=True, readonly=True)

    _service_code_unique = models.Constraint(
        "unique(campaign_id, service_code)", "Referral service codes must be unique per campaign."
    )

    @api.model_create_multi
    def create(self, values_list):
        prepared = []
        for original in values_list:
            values = dict(original)
            values["service_code"] = str(values.get("service_code") or "").strip().upper()
            prepared.append(values)
        records = super().create(prepared)
        records._check_referral_route()
        return records

    def write(self, values):
        result = super().write(values)
        self._check_referral_route()
        return result

    @api.constrains("campaign_id", "destination_campaign_id", "allowed_payload_keys", "delivery_enabled")
    def _check_referral_route(self):
        for route in self:
            if route.destination_campaign_id == route.campaign_id:
                raise ValidationError(_("Use a live-transfer route inside one campaign."))
            keys = route.allowed_payload_keys or []
            if not isinstance(keys, list) or not set(keys).issubset(SAFE_REFERRAL_KEYS):
                raise ValidationError(_("Referral routes may allow only the approved minimum fields."))
            if route.delivery_enabled:
                raise ValidationError(_("External referral delivery remains disabled in staging."))


class CcReferral(models.Model):
    _name = "cc.referral"
    _description = "Controlled Referral Request"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "requested_at desc, id desc"

    operation_uuid = fields.Char(
        string="Referral UUID", required=True, default=lambda self: str(uuid.uuid4()),
        readonly=True, copy=False, index=True,
    )
    requester_membership_id = fields.Many2one(
        "cc.campaign.membership", required=True, readonly=True, ondelete="restrict"
    )
    customer_profile_id = fields.Many2one(
        "cc.customer.profile", required=True, readonly=True, ondelete="restrict"
    )
    route_id = fields.Many2one(
        "cc.referral.route",
        required=True,
        readonly=True,
        ondelete="restrict",
    )
    destination_service_code = fields.Char(required=True, readonly=True, index=True)
    destination_service_label = fields.Char(required=True, readonly=True)
    consent_reference_hash = fields.Char(required=True, size=64, readonly=True)
    request_summary = fields.Char(required=True, readonly=True)
    payload_hash = fields.Char(required=True, size=64, readonly=True)
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("destination_created", "Destination Record Created"),
            ("accepted", "Accepted"),
            ("declined", "Declined"),
            ("cancelled", "Cancelled"),
            ("suppressed", "Suppressed"),
        ],
        required=True,
        default="pending",
        readonly=True,
        index=True,
    )
    safe_status = fields.Char(required=True, default="Referral pending.", readonly=True)
    requested_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    idempotency_key = fields.Char(required=True, readonly=True, copy=False, index=True)
    correlation_id = fields.Char(required=True, readonly=True, copy=False, index=True)

    _operation_uuid_unique = models.Constraint(
        "unique(operation_uuid)", "Referral UUIDs must be unique."
    )
    _referral_idempotency_unique = models.Constraint(
        "unique(idempotency_key)", "Referral idempotency keys must be unique."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_referral_write_capability") is not REFERRAL_WRITE_CAPABILITY:
            raise AccessError(_("Referrals require the governed request service."))
        records = super().create(values_list)
        records._check_referral_scope()
        return records.with_env(records.env(context=dict(records.env.context, _cc_referral_write_capability=None)))

    def write(self, values):
        if self.env.context.get("_cc_referral_write_capability") is not REFERRAL_WRITE_CAPABILITY:
            raise AccessError(_("Referral state requires the privileged service."))
        return super().write(values)

    def unlink(self):
        raise AccessError(_("Referral evidence cannot be deleted."))

    def copy(self, default=None):
        raise AccessError(_("Referrals cannot be copied."))

    @api.constrains("campaign_id", "requester_membership_id", "customer_profile_id", "route_id")
    def _check_referral_scope(self):
        for referral in self:
            if referral.requester_membership_id.campaign_id != referral.campaign_id:
                raise ValidationError(_("Referral requester belongs to another campaign."))
            if referral.customer_profile_id.campaign_id != referral.campaign_id:
                raise ValidationError(_("Referral customer profile belongs to another campaign."))
            if referral.route_id.campaign_id != referral.campaign_id:
                raise ValidationError(_("Referral route belongs to another source campaign."))

    @api.model
    def request_referral(
        self,
        *,
        campaign_id,
        customer_profile_id,
        service_code,
        consent_reference,
        minimal_payload,
        idempotency_key,
        correlation_id,
    ):
        campaign = _resolve_campaign(self.env, campaign_id)
        membership = _active_membership(
            self.env, campaign, allowed_roles={"agent", "senior_agent", "supervisor"}
        )
        profile = self.env["cc.customer.profile"].browse(customer_profile_id).exists()
        if not profile:
            raise ValidationError(_("A campaign customer profile is required."))
        profile.check_access("read")
        route = self.env["cc.referral.route"].search(
            [("campaign_id", "=", campaign.id), ("service_code", "=", str(service_code or "").strip().upper()), ("active", "=", True)],
            limit=1,
        )
        if not route:
            raise ValidationError(_("The requested referral service is not approved."))
        consent_reference = str(consent_reference or "").strip()
        if not consent_reference:
            raise ValidationError(_("Explicit customer consent evidence is required."))
        if not isinstance(minimal_payload, dict) or not minimal_payload:
            raise ValidationError(_("Referral payload must contain approved minimum data."))
        normalized_keys = {str(key).strip().lower() for key in minimal_payload}
        if normalized_keys.intersection(FORBIDDEN_KEYS) or not normalized_keys.issubset(
            set(route.allowed_payload_keys or [])
        ):
            raise ValidationError(_("Referral payload exceeds the approved minimum fields."))
        if len(_canonical_json(minimal_payload)) > 4096:
            raise ValidationError(_("Referral payload exceeds the safe size limit."))
        existing = self.search([("idempotency_key", "=", idempotency_key)], limit=1)
        payload_hash = _digest(minimal_payload)
        if existing:
            if existing.payload_hash != payload_hash or existing.customer_profile_id != profile:
                raise ValidationError(_("Referral idempotency binding conflict."))
            return existing
        summary = str(minimal_payload.get("request_summary") or "Referral requested").strip()
        referral = self.with_context(_cc_referral_write_capability=REFERRAL_WRITE_CAPABILITY).create(
            {
                "campaign_id": campaign.id,
                "requester_membership_id": membership.id,
                "customer_profile_id": profile.id,
                "route_id": route.id,
                "destination_service_code": route.service_code,
                "destination_service_label": route.service_label,
                "consent_reference_hash": hashlib.sha256(consent_reference.encode("utf-8")).hexdigest(),
                "request_summary": summary[:240],
                "payload_hash": payload_hash,
                "idempotency_key": idempotency_key,
                "correlation_id": correlation_id,
            }
        )
        payload = {
            "referral_uuid": referral.operation_uuid,
            "source_campaign_code": campaign.code,
            "destination_service_code": route.service_code,
            "consent_reference_hash": referral.consent_reference_hash,
            "payload_hash": payload_hash,
        }
        self.env["cc.operation.outbox"]._emit(
            referral,
            "cc.referral.requested.v1",
            idempotency_key,
            correlation_id,
            payload,
            "referral_delivery_disabled",
        )
        return referral

    def action_materialize_destination(self, minimal_payload, event_id):
        if not _is_service(self.env.user):
            raise AccessError(_("Only the privileged call service may create destination referrals."))
        if not isinstance(minimal_payload, dict) or _digest(minimal_payload) not in self.mapped("payload_hash"):
            raise ValidationError(_("Destination payload does not match the approved referral."))
        deliveries = self.env["cc.referral.delivery"]
        for referral in self:
            if _digest(minimal_payload) != referral.payload_hash:
                raise ValidationError(_("Destination payload binding conflict."))
            delivery = self.env["cc.referral.delivery"].search(
                [("operation_uuid", "=", referral.operation_uuid)], limit=1
            )
            if delivery:
                if delivery.payload_hash != referral.payload_hash or delivery.event_id != event_id:
                    raise ValidationError(_("Referral destination idempotency conflict."))
            else:
                delivery = self.env["cc.referral.delivery"].with_context(
                    _cc_referral_delivery_capability=REFERRAL_DELIVERY_CAPABILITY
                ).create(
                    {
                        "campaign_id": referral.route_id.destination_campaign_id.id,
                        "operation_uuid": referral.operation_uuid,
                        "source_referral_id": referral.id,
                        "source_campaign_code": referral.campaign_id.code,
                        "service_code": referral.destination_service_code,
                        "minimal_payload": minimal_payload,
                        "payload_hash": referral.payload_hash,
                        "event_id": event_id,
                    }
                )
            referral.with_context(_cc_referral_write_capability=REFERRAL_WRITE_CAPABILITY).write(
                {"state": "destination_created", "safe_status": "Referral delivered to the requested service."}
            )
            deliveries |= delivery
        return deliveries

    def action_record_status(self, status):
        if not _is_service(self.env.user):
            raise AccessError(_("Only the privileged call service may update referral status."))
        if status not in {"accepted", "declined", "suppressed"}:
            raise ValidationError(_("Unsupported referral status."))
        self.with_context(_cc_referral_write_capability=REFERRAL_WRITE_CAPABILITY).write(
            {"state": status, "safe_status": f"Referral {status}."}
        )
        return True


class CcReferralDelivery(models.Model):
    _name = "cc.referral.delivery"
    _description = "Destination Campaign Referral"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "created_at desc, id desc"

    operation_uuid = fields.Char(required=True, readonly=True, copy=False, index=True)
    source_referral_id = fields.Many2one(
        "cc.referral", required=True, readonly=True, ondelete="restrict",
        groups="codestra_cc_calls.group_cc_call_service,codestra_cc_security.group_cc_global_administrator",
    )
    source_campaign_code = fields.Char(
        required=True, readonly=True,
        groups="codestra_cc_calls.group_cc_call_service,codestra_cc_security.group_cc_global_administrator",
    )
    service_code = fields.Char(required=True, readonly=True, index=True)
    minimal_payload = fields.Json(readonly=True)
    payload_hash = fields.Char(required=True, readonly=True, size=64)
    event_id = fields.Char(required=True, readonly=True, copy=False, index=True)
    state = fields.Selection(
        [("new", "New"), ("accepted", "Accepted"), ("declined", "Declined"), ("suppressed", "Suppressed")],
        required=True, default="new", readonly=True,
    )
    created_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)

    _operation_uuid_unique = models.Constraint(
        "unique(operation_uuid)", "Destination referrals must be exactly once."
    )
    _event_id_unique = models.Constraint(
        "unique(event_id)", "Referral delivery events must be exactly once."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_referral_delivery_capability") is not REFERRAL_DELIVERY_CAPABILITY:
            raise AccessError(_("Destination referrals require the privileged service."))
        records = super().create(values_list)
        records._check_delivery_scope()
        return records.with_env(records.env(context=dict(records.env.context, _cc_referral_delivery_capability=None)))

    def write(self, values):
        raise AccessError(_("Destination referral identity is immutable."))

    def unlink(self):
        raise AccessError(_("Destination referrals cannot be deleted."))

    @api.constrains("campaign_id", "source_referral_id", "payload_hash", "minimal_payload")
    def _check_delivery_scope(self):
        for delivery in self:
            source = delivery.source_referral_id
            if source.route_id.destination_campaign_id != delivery.campaign_id:
                raise ValidationError(_("Referral delivery belongs to the wrong destination campaign."))
            if source.campaign_id == delivery.campaign_id:
                raise ValidationError(_("Same-campaign handoffs must use a transfer."))
            if delivery.payload_hash != _digest(delivery.minimal_payload or {}):
                raise ValidationError(_("Referral delivery payload hash mismatch."))
