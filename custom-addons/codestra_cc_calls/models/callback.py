import hashlib
import json
import uuid
from datetime import timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


CALL_WRITE_CAPABILITY = object()
OUTBOX_WRITE_CAPABILITY = object()
REMINDER_WRITE_CAPABILITY = object()

OPERATIONAL_GROUPS = (
    "codestra_cc_security.group_cc_campaign_agent",
    "codestra_cc_security.group_cc_senior_agent",
    "codestra_cc_security.group_cc_campaign_supervisor",
)
CALLBACK_TYPES = [
    ("customer", "Customer-Specific"),
    ("agent", "Agent-Specific"),
    ("queue", "Campaign Queue"),
    ("appointment", "Appointment"),
    ("transfer_recovery", "Transfer Recovery"),
]
CALLBACK_STATES = [
    ("draft", "Draft"),
    ("scheduled", "Scheduled"),
    ("ready", "Ready"),
    ("in_progress", "In Progress"),
    ("completed", "Completed"),
    ("missed", "Missed"),
    ("recovery", "Recovery Queue"),
    ("cancelled", "Cancelled"),
    ("blocked", "Blocked"),
]
CALLBACK_TRANSITIONS = {
    "draft": {"scheduled", "cancelled", "blocked"},
    "scheduled": {"ready", "missed", "cancelled", "blocked"},
    "ready": {"in_progress", "missed", "cancelled", "blocked"},
    "in_progress": {"completed", "missed", "blocked"},
    "missed": {"recovery", "in_progress", "cancelled"},
    "recovery": {"scheduled", "in_progress", "cancelled", "blocked"},
    "blocked": {"draft", "cancelled"},
    "completed": set(),
    "cancelled": set(),
}
APPOINTMENT_STATES = [
    ("draft", "Draft"),
    ("scheduled", "Scheduled"),
    ("confirmed", "Confirmed"),
    ("preparing", "Preparing"),
    ("in_progress", "In Progress"),
    ("completed", "Completed"),
    ("missed", "Missed"),
    ("cancelled", "Cancelled"),
]


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value):
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _is_operational(user):
    return any(user.has_group(xmlid) for xmlid in OPERATIONAL_GROUPS)


def _is_global_admin(user):
    return user.has_group("codestra_cc_security.group_cc_global_administrator")


def _is_service(user):
    return user.has_group("codestra_cc_calls.group_cc_call_service")


def _resolve_campaign(env, supplied_campaign_id=False, record=False):
    if _is_operational(env.user) and not _is_global_admin(env.user):
        campaign = env.user._cc_resolve_operational_membership().campaign_id
        if supplied_campaign_id and supplied_campaign_id != campaign.id:
            raise AccessError(_("The authenticated membership determines campaign scope."))
        if record and record.campaign_id != campaign:
            raise AccessError(_("The operation belongs to another campaign."))
        return campaign
    if record:
        if supplied_campaign_id and supplied_campaign_id != record.campaign_id.id:
            raise AccessError(_("The supplied campaign does not own this operation."))
        record.campaign_id.check_access("read")
        return record.campaign_id
    campaign = env["cc.campaign"].browse(supplied_campaign_id).exists()
    if not campaign:
        raise ValidationError(_("A canonical campaign workspace is required."))
    campaign.check_access("read")
    return campaign


def _active_membership(env, campaign, user=False, allowed_roles=None):
    user = user or env.user
    domain = [
        ("campaign_id", "=", campaign.id),
        ("user_id", "=", user.id),
        ("state", "=", "active"),
    ]
    if allowed_roles:
        domain.append(("role", "in", tuple(allowed_roles)))
    membership = env["cc.campaign.membership"].search(domain, limit=1)
    if not membership:
        raise ValidationError(_("Assignment requires an active same-campaign membership."))
    return membership


def _timezone(value):
    try:
        return ZoneInfo(str(value or ""))
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationError(_("A valid IANA customer time zone is required."))


class CcCallbackPolicy(models.Model):
    _name = "cc.callback.policy"
    _description = "Campaign Callback Policy"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "campaign_id, name"

    name = fields.Char(required=True)
    timezone = fields.Char(required=True, default="UTC")
    allowed_weekdays = fields.Json(default=lambda self: [0, 1, 2, 3, 4])
    calling_hour_start = fields.Float(required=True, default=9.0)
    calling_hour_end = fields.Float(required=True, default=17.0)
    max_attempts = fields.Integer(required=True, default=3)
    reminder_minutes = fields.Integer(required=True, default=15)
    missed_recovery_minutes = fields.Integer(required=True, default=5)
    active = fields.Boolean(default=False, required=True)
    publication_enabled = fields.Boolean(default=False, required=True, readonly=True)

    _one_active_campaign_policy = models.UniqueIndex(
        "(campaign_id) WHERE active",
        "A campaign may have only one active callback policy.",
    )
    _valid_attempts = models.Constraint(
        "check(max_attempts > 0 and max_attempts <= 20)",
        "Callback attempts must be between one and twenty.",
    )
    _valid_hours = models.Constraint(
        "check(calling_hour_start >= 0 and calling_hour_start < calling_hour_end and calling_hour_end <= 24)",
        "Callback calling hours must be ordered within one day.",
    )

    @api.constrains("timezone", "allowed_weekdays", "publication_enabled")
    def _check_policy(self):
        for policy in self:
            _timezone(policy.timezone)
            days = policy.allowed_weekdays or []
            if not isinstance(days, list) or not days or any(
                not isinstance(day, int) or day < 0 or day > 6 for day in days
            ):
                raise ValidationError(_("Allowed weekdays must contain values zero through six."))
            if policy.publication_enabled:
                raise ValidationError(_("Callback publication remains disabled in staging."))


class CcOperationOutbox(models.Model):
    _name = "cc.operation.outbox"
    _description = "Immutable Call Operation Desired-State Outbox"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "created_at desc, id desc"

    event_uuid = fields.Char(required=True, readonly=True, copy=False, index=True)
    aggregate_model = fields.Char(required=True, readonly=True, index=True)
    aggregate_id = fields.Integer(required=True, readonly=True, index=True)
    aggregate_uuid = fields.Char(required=True, readonly=True, index=True)
    event_type = fields.Char(required=True, readonly=True, index=True)
    schema_version = fields.Char(required=True, readonly=True, default="1.0")
    idempotency_key = fields.Char(required=True, readonly=True, copy=False, index=True)
    correlation_id = fields.Char(required=True, readonly=True, copy=False, index=True)
    actor_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict", index=True
    )
    payload = fields.Json(readonly=True)
    payload_hash = fields.Char(required=True, readonly=True, size=64)
    delivery_state = fields.Selection(
        [("held", "Held"), ("acknowledged", "Acknowledged")],
        required=True,
        default="held",
        readonly=True,
        index=True,
    )
    hold_reason = fields.Selection(
        [
            ("callback_publication_disabled", "Callback Publication Disabled"),
            ("warm_transfer_disabled", "Warm Transfer Disabled"),
            ("referral_delivery_disabled", "Referral Delivery Disabled"),
        ],
        required=True,
        readonly=True,
    )
    created_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)

    _event_uuid_unique = models.Constraint(
        "unique(event_uuid)", "Call-operation event UUIDs must be unique."
    )
    _idempotency_unique = models.Constraint(
        "unique(idempotency_key)", "Call-operation idempotency keys must be unique."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_operation_outbox_capability") is not OUTBOX_WRITE_CAPABILITY:
            raise AccessError(_("Operation outbox rows require the governed producer."))
        records = super().create(values_list)
        return records.with_env(records.env(context=dict(records.env.context, _cc_operation_outbox_capability=None)))

    def write(self, values):
        raise AccessError(_("Operation outbox evidence is immutable."))

    def unlink(self):
        raise AccessError(_("Operation outbox evidence cannot be deleted."))

    @api.model
    def _emit(self, aggregate, event_type, idempotency_key, correlation_id, payload, hold_reason):
        aggregate.ensure_one()
        event_key = f"{aggregate._name}:{aggregate.operation_uuid}:{event_type}:{idempotency_key}"
        event_uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, event_key))
        payload_hash = _digest(payload)
        existing = self.search([("event_uuid", "=", event_uuid)], limit=1)
        if existing:
            if existing.payload_hash != payload_hash or existing.aggregate_id != aggregate.id:
                raise ValidationError(_("Immutable operation event binding conflict."))
            return existing
        return self.with_context(_cc_operation_outbox_capability=OUTBOX_WRITE_CAPABILITY).create(
            {
                "campaign_id": aggregate.campaign_id.id,
                "event_uuid": event_uuid,
                "aggregate_model": aggregate._name,
                "aggregate_id": aggregate.id,
                "aggregate_uuid": aggregate.operation_uuid,
                "event_type": event_type,
                "idempotency_key": idempotency_key,
                "correlation_id": correlation_id,
                "actor_id": self.env.user.id,
                "payload": payload,
                "payload_hash": payload_hash,
                "hold_reason": hold_reason,
            }
        )


class CcCallback(models.Model):
    _name = "cc.callback"
    _description = "Campaign Callback"
    _inherit = ["cc.campaign.scoped.mixin", "mail.thread"]
    _order = "priority desc, scheduled_at, id"

    operation_uuid = fields.Char(
        string="Callback UUID",
        required=True,
        default=lambda self: str(uuid.uuid4()),
        readonly=True,
        copy=False,
        index=True,
    )
    name = fields.Char(required=True, tracking=True)
    callback_type = fields.Selection(CALLBACK_TYPES, required=True, default="customer", index=True)
    customer_profile_id = fields.Many2one(
        "cc.customer.profile", required=True, ondelete="restrict", index=True
    )
    lead_id = fields.Many2one("crm.lead", ondelete="restrict", index=True)
    source_call_unique_id = fields.Char(required=True, index=True)
    assigned_membership_id = fields.Many2one(
        "cc.campaign.membership", ondelete="restrict", index=True
    )
    queue_code = fields.Char(index=True)
    supervisor_membership_id = fields.Many2one(
        "cc.campaign.membership", required=True, ondelete="restrict", index=True
    )
    scheduled_at = fields.Datetime(required=True, tracking=True, index=True)
    customer_timezone = fields.Char(required=True)
    reason = fields.Char(required=True, tracking=True)
    priority = fields.Selection(
        [("low", "Low"), ("normal", "Normal"), ("high", "High"), ("urgent", "Urgent")],
        required=True,
        default="normal",
        index=True,
    )
    consent_state = fields.Selection(
        [("unknown", "Unknown"), ("captured", "Captured"), ("revoked", "Revoked"), ("suppressed", "Suppressed")],
        required=True,
        default="unknown",
        index=True,
    )
    preferred_channel = fields.Selection(
        [("phone", "Phone"), ("sms", "SMS"), ("email", "Email")],
        required=True,
        default="phone",
    )
    policy_id = fields.Many2one("cc.callback.policy", required=True, ondelete="restrict")
    appointment_id = fields.Many2one("cc.appointment", ondelete="restrict", index=True)
    state = fields.Selection(CALLBACK_STATES, required=True, default="draft", tracking=True, index=True)
    attempt_count = fields.Integer(required=True, default=0)
    last_result = fields.Char(readonly=True)
    next_action = fields.Char(readonly=True)
    middleware_idempotency_key = fields.Char(required=True, readonly=True, copy=False, index=True)
    correlation_id = fields.Char(required=True, readonly=True, copy=False, index=True)
    publication_state = fields.Selection(
        [("held", "Held"), ("readback_matched", "Read-Back Matched")],
        required=True,
        default="held",
        readonly=True,
        index=True,
    )
    vicidial_readback_reference = fields.Char(readonly=True, copy=False)
    version = fields.Integer(required=True, default=1, readonly=True)
    history_ids = fields.One2many("cc.callback.history", "callback_id", readonly=True)
    reminder_ids = fields.One2many("cc.reminder", "callback_id", readonly=True)

    _operation_uuid_unique = models.Constraint(
        "unique(operation_uuid)", "Callback UUIDs must be unique."
    )
    _callback_idempotency_unique = models.Constraint(
        "unique(middleware_idempotency_key)", "Callback idempotency keys must be unique."
    )
    _attempt_nonnegative = models.Constraint(
        "check(attempt_count >= 0)", "Callback attempt counts cannot be negative."
    )

    @api.model_create_multi
    def create(self, values_list):
        prepared = []
        internal = self.env.context.get("_cc_call_write_capability") is CALL_WRITE_CAPABILITY
        for original in values_list:
            values = dict(original)
            campaign = _resolve_campaign(self.env, values.get("campaign_id"))
            values["campaign_id"] = campaign.id
            values.setdefault("middleware_idempotency_key", str(uuid.uuid4()))
            values.setdefault("correlation_id", values["middleware_idempotency_key"])
            if not values.get("assigned_membership_id") and _is_operational(self.env.user):
                values["assigned_membership_id"] = _active_membership(
                    self.env, campaign, allowed_roles={"agent", "senior_agent", "supervisor"}
                ).id
            if not values.get("supervisor_membership_id"):
                supervisor = campaign.primary_supervisor_membership_id
                if supervisor:
                    values["supervisor_membership_id"] = supervisor.id
            if internal and values.get("state") not in (None, "scheduled"):
                raise ValidationError(_("Internal appointment callbacks start scheduled."))
            prepared.append(values)
        records = super().create(prepared)
        records._check_callback_scope()
        return records.with_env(records.env(context=dict(records.env.context, _cc_call_write_capability=None)))

    def write(self, values):
        protected = {
            "campaign_id", "operation_uuid", "customer_profile_id", "source_call_unique_id",
            "middleware_idempotency_key", "correlation_id", "publication_state",
            "vicidial_readback_reference", "version", "state", "attempt_count",
            "last_result", "next_action", "appointment_id",
        }
        if protected.intersection(values) and self.env.context.get("_cc_call_write_capability") is not CALL_WRITE_CAPABILITY:
            raise AccessError(_("Callback identity and lifecycle require governed actions."))
        result = super().write(values)
        self._check_callback_scope()
        return result

    def unlink(self):
        raise AccessError(_("Callbacks are retained as campaign evidence."))

    def copy(self, default=None):
        raise AccessError(_("Callbacks cannot be copied."))

    def export_data(self, fields_to_export, raw_data=False):
        if _is_operational(self.env.user):
            raise UserError(_("Operational callback export is disabled."))
        return super().export_data(fields_to_export, raw_data=raw_data)

    @api.constrains(
        "campaign_id", "customer_profile_id", "lead_id", "assigned_membership_id",
        "supervisor_membership_id", "policy_id", "appointment_id", "callback_type",
    )
    def _check_callback_scope(self):
        for callback in self:
            if callback.customer_profile_id.campaign_id != callback.campaign_id:
                raise ValidationError(_("Callback and customer profile campaigns differ."))
            if callback.lead_id and callback.lead_id.campaign_id != callback.campaign_id:
                raise ValidationError(_("Callback and CRM lead campaigns differ."))
            if callback.assigned_membership_id and (
                callback.assigned_membership_id.campaign_id != callback.campaign_id
                or callback.assigned_membership_id.state != "active"
            ):
                raise ValidationError(_("Callback assignment must remain in its campaign."))
            if callback.supervisor_membership_id.campaign_id != callback.campaign_id or (
                callback.supervisor_membership_id.state != "active"
                or callback.supervisor_membership_id.role != "supervisor"
                or not callback.supervisor_membership_id.is_primary_supervisor
            ):
                raise ValidationError(_("Callback recovery requires the campaign's primary supervisor."))
            if callback.policy_id.campaign_id != callback.campaign_id or not callback.policy_id.active:
                raise ValidationError(_("Callback policy must be active in the same campaign."))
            if bool(callback.assigned_membership_id) == bool(callback.queue_code):
                raise ValidationError(_("Choose exactly one assigned membership or campaign queue."))
            if callback.callback_type == "appointment" and not callback.appointment_id:
                raise ValidationError(_("Appointment callbacks require an appointment."))
            if callback.appointment_id and callback.appointment_id.campaign_id != callback.campaign_id:
                raise ValidationError(_("Appointment and callback campaigns differ."))

    def _validate_scheduled_time(self):
        self.ensure_one()
        policy = self.policy_id
        zone = _timezone(self.customer_timezone)
        scheduled = fields.Datetime.to_datetime(self.scheduled_at)
        if not scheduled:
            raise ValidationError(_("A callback schedule is required."))
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=timezone.utc)
        local = scheduled.astimezone(zone)
        local_hour = local.hour + local.minute / 60.0
        if local.weekday() not in (policy.allowed_weekdays or []):
            raise ValidationError(_("The callback is outside approved calling days."))
        if not policy.calling_hour_start <= local_hour < policy.calling_hour_end:
            raise ValidationError(_("The callback is outside approved local calling hours."))
        if self.consent_state != "captured":
            raise ValidationError(_("Captured callback consent is required."))

    def _transition(self, target, event_suffix, result=False):
        for callback in self:
            _resolve_campaign(self.env, callback.campaign_id.id, record=callback)
            if target not in CALLBACK_TRANSITIONS.get(callback.state, set()):
                raise ValidationError(
                    _("Invalid callback transition from %(source)s to %(target)s.", source=callback.state, target=target)
                )
            if target == "scheduled":
                callback._validate_scheduled_time()
            previous = callback.state
            values = {"state": target, "version": callback.version + 1}
            if result:
                values["last_result"] = result
            if target in {"missed", "recovery"}:
                values["next_action"] = "same_campaign_supervisor_recovery"
            callback.with_context(_cc_call_write_capability=CALL_WRITE_CAPABILITY).write(values)
            self.env["cc.callback.history"]._append(callback, previous, target, event_suffix)
        return True

    def action_schedule(self):
        self._transition("scheduled", "scheduled")
        for callback in self:
            payload = {
                "callback_uuid": callback.operation_uuid,
                "campaign_code": callback.campaign_id.code,
                "callback_type": callback.callback_type,
                "scheduled_at": fields.Datetime.to_string(callback.scheduled_at),
                "customer_timezone": callback.customer_timezone,
                "assignment": "agent" if callback.assigned_membership_id else "queue",
                "consent_state": callback.consent_state,
            }
            self.env["cc.operation.outbox"]._emit(
                callback,
                "cc.callback.scheduled.v1",
                callback.middleware_idempotency_key,
                callback.correlation_id,
                payload,
                "callback_publication_disabled",
            )
            self.env["cc.reminder"]._schedule_for_callback(callback)
        return True

    def action_ready(self):
        return self._transition("ready", "ready")

    def action_start(self):
        return self._transition("in_progress", "started")

    def action_complete(self, result="completed"):
        return self._transition("completed", "completed", result=result)

    def action_mark_missed(self, result="missed"):
        return self._transition("missed", "missed", result=result)

    def action_recover(self):
        return self._transition("recovery", "recovery_queued")

    def action_cancel(self):
        return self._transition("cancelled", "cancelled")

    def action_publish(self):
        raise UserError(_("CC_ENABLE_CALLBACK_PUBLICATION is false; publication is blocked."))

    def action_record_readback(self, external_reference, event_id):
        if not _is_service(self.env.user):
            raise AccessError(_("Only the call integration service may record read-back."))
        external_reference = str(external_reference or "").strip()
        event_id = str(event_id or "").strip()
        if not external_reference or not event_id:
            raise ValidationError(_("Read-back reference and event ID are required."))
        for callback in self:
            existing = callback.history_ids.filtered(lambda row: row.event_id == event_id)
            if existing:
                if callback.vicidial_readback_reference != external_reference:
                    raise ValidationError(_("Read-back event binding conflict."))
                continue
            callback.with_context(_cc_call_write_capability=CALL_WRITE_CAPABILITY).write(
                {
                    "publication_state": "readback_matched",
                    "vicidial_readback_reference": external_reference,
                    "version": callback.version + 1,
                }
            )
            self.env["cc.callback.history"]._append(
                callback, callback.state, callback.state, "readback_matched", event_id=event_id
            )
        return True


class CcCallbackHistory(models.Model):
    _name = "cc.callback.history"
    _description = "Immutable Callback History"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "occurred_at desc, id desc"

    callback_id = fields.Many2one("cc.callback", required=True, ondelete="restrict", index=True)
    event_id = fields.Char(required=True, readonly=True, copy=False, index=True)
    event_type = fields.Char(required=True, readonly=True, index=True)
    from_state = fields.Char(readonly=True)
    to_state = fields.Char(readonly=True)
    actor_id = fields.Many2one("res.users", required=True, readonly=True, ondelete="restrict")
    occurred_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)

    _callback_event_unique = models.Constraint(
        "unique(callback_id, event_id)", "Callback events must be exactly once."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_call_write_capability") is not CALL_WRITE_CAPABILITY:
            raise AccessError(_("Callback history requires the governed lifecycle."))
        records = super().create(values_list)
        return records.with_env(records.env(context=dict(records.env.context, _cc_call_write_capability=None)))

    def write(self, values):
        raise AccessError(_("Callback history is append-only."))

    def unlink(self):
        raise AccessError(_("Callback history cannot be deleted."))

    @api.model
    def _append(self, callback, source, target, suffix, event_id=False):
        event_id = event_id or str(
            uuid.uuid5(uuid.UUID(callback.operation_uuid), f"{callback.version}:{suffix}")
        )
        existing = self.search([("callback_id", "=", callback.id), ("event_id", "=", event_id)], limit=1)
        if existing:
            return existing
        return self.with_context(_cc_call_write_capability=CALL_WRITE_CAPABILITY).create(
            {
                "campaign_id": callback.campaign_id.id,
                "callback_id": callback.id,
                "event_id": event_id,
                "event_type": f"cc.callback.{suffix}.v1",
                "from_state": source,
                "to_state": target,
                "actor_id": self.env.user.id,
            }
        )


class CcAppointment(models.Model):
    _name = "cc.appointment"
    _description = "Campaign Appointment"
    _inherit = ["cc.campaign.scoped.mixin", "mail.thread"]
    _order = "scheduled_start, id"

    operation_uuid = fields.Char(
        string="Appointment UUID", required=True, default=lambda self: str(uuid.uuid4()),
        readonly=True, copy=False, index=True,
    )
    name = fields.Char(required=True, tracking=True)
    customer_profile_id = fields.Many2one("cc.customer.profile", required=True, ondelete="restrict")
    lead_id = fields.Many2one("crm.lead", ondelete="restrict")
    assigned_membership_id = fields.Many2one("cc.campaign.membership", required=True, ondelete="restrict")
    supervisor_membership_id = fields.Many2one("cc.campaign.membership", required=True, ondelete="restrict")
    policy_id = fields.Many2one("cc.callback.policy", required=True, ondelete="restrict")
    scheduled_start = fields.Datetime(required=True, tracking=True, index=True)
    scheduled_end = fields.Datetime(required=True, tracking=True)
    customer_timezone = fields.Char(required=True)
    reason = fields.Char(required=True)
    preparation_notes = fields.Text()
    consent_state = fields.Selection(
        [("unknown", "Unknown"), ("captured", "Captured"), ("revoked", "Revoked"), ("suppressed", "Suppressed")],
        required=True, default="unknown",
    )
    priority = fields.Selection(
        [("low", "Low"), ("normal", "Normal"), ("high", "High"), ("urgent", "Urgent")],
        required=True, default="normal",
    )
    state = fields.Selection(APPOINTMENT_STATES, required=True, default="draft", tracking=True, index=True)
    callback_id = fields.Many2one("cc.callback", readonly=True, ondelete="restrict", copy=False)
    correlation_id = fields.Char(required=True, default=lambda self: str(uuid.uuid4()), readonly=True, copy=False)
    version = fields.Integer(required=True, default=1, readonly=True)
    reminder_ids = fields.One2many("cc.reminder", "appointment_id", readonly=True)

    _operation_uuid_unique = models.Constraint(
        "unique(operation_uuid)", "Appointment UUIDs must be unique."
    )

    @api.model_create_multi
    def create(self, values_list):
        prepared = []
        for original in values_list:
            values = dict(original)
            campaign = _resolve_campaign(self.env, values.get("campaign_id"))
            values["campaign_id"] = campaign.id
            if not values.get("assigned_membership_id") and _is_operational(self.env.user):
                values["assigned_membership_id"] = _active_membership(
                    self.env, campaign, allowed_roles={"agent", "senior_agent", "supervisor"}
                ).id
            if not values.get("supervisor_membership_id"):
                supervisor = campaign.primary_supervisor_membership_id
                if supervisor:
                    values["supervisor_membership_id"] = supervisor.id
            prepared.append(values)
        records = super().create(prepared)
        records._check_appointment_scope()
        return records

    def write(self, values):
        protected = {"campaign_id", "operation_uuid", "customer_profile_id", "callback_id", "state", "version", "correlation_id"}
        if protected.intersection(values) and self.env.context.get("_cc_call_write_capability") is not CALL_WRITE_CAPABILITY:
            raise AccessError(_("Appointment identity and lifecycle require governed actions."))
        result = super().write(values)
        self._check_appointment_scope()
        return result

    def unlink(self):
        raise AccessError(_("Appointments are retained as campaign evidence."))

    def copy(self, default=None):
        raise AccessError(_("Appointments cannot be copied."))

    def export_data(self, fields_to_export, raw_data=False):
        if _is_operational(self.env.user):
            raise UserError(_("Operational appointment export is disabled."))
        return super().export_data(fields_to_export, raw_data=raw_data)

    @api.constrains(
        "campaign_id", "customer_profile_id", "lead_id", "assigned_membership_id",
        "supervisor_membership_id", "policy_id", "scheduled_start", "scheduled_end",
    )
    def _check_appointment_scope(self):
        for appointment in self:
            if appointment.customer_profile_id.campaign_id != appointment.campaign_id:
                raise ValidationError(_("Appointment and customer profile campaigns differ."))
            if appointment.lead_id and appointment.lead_id.campaign_id != appointment.campaign_id:
                raise ValidationError(_("Appointment and CRM lead campaigns differ."))
            if appointment.assigned_membership_id.campaign_id != appointment.campaign_id or appointment.assigned_membership_id.state != "active":
                raise ValidationError(_("Appointment assignment must remain in its campaign."))
            if appointment.supervisor_membership_id.campaign_id != appointment.campaign_id or (
                appointment.supervisor_membership_id.role != "supervisor"
                or appointment.supervisor_membership_id.state != "active"
                or not appointment.supervisor_membership_id.is_primary_supervisor
            ):
                raise ValidationError(_("Appointment requires the campaign's primary supervisor."))
            if appointment.policy_id.campaign_id != appointment.campaign_id or not appointment.policy_id.active:
                raise ValidationError(_("Appointment callback policy must be active in the same campaign."))
            if appointment.scheduled_end <= appointment.scheduled_start:
                raise ValidationError(_("Appointment end must be after its start."))
            _timezone(appointment.customer_timezone)

    def action_schedule(self):
        for appointment in self:
            _resolve_campaign(self.env, appointment.campaign_id.id, record=appointment)
            if appointment.state != "draft":
                raise ValidationError(_("Only draft appointments can be scheduled."))
            callback = self.env["cc.callback"].with_context(
                _cc_call_write_capability=CALL_WRITE_CAPABILITY
            ).create(
                {
                    "campaign_id": appointment.campaign_id.id,
                    "name": appointment.name,
                    "callback_type": "appointment",
                    "customer_profile_id": appointment.customer_profile_id.id,
                    "lead_id": appointment.lead_id.id,
                    "source_call_unique_id": f"appointment:{appointment.operation_uuid}",
                    "assigned_membership_id": appointment.assigned_membership_id.id,
                    "supervisor_membership_id": appointment.supervisor_membership_id.id,
                    "scheduled_at": appointment.scheduled_start,
                    "customer_timezone": appointment.customer_timezone,
                    "reason": appointment.reason,
                    "priority": appointment.priority,
                    "consent_state": appointment.consent_state,
                    "preferred_channel": "phone",
                    "policy_id": appointment.policy_id.id,
                    "appointment_id": appointment.id,
                    "state": "scheduled",
                    "middleware_idempotency_key": f"appointment:{appointment.operation_uuid}:callback",
                    "correlation_id": appointment.correlation_id,
                }
            )
            callback._validate_scheduled_time()
            appointment.with_context(_cc_call_write_capability=CALL_WRITE_CAPABILITY).write(
                {"state": "scheduled", "callback_id": callback.id, "version": appointment.version + 1}
            )
            payload = {
                "callback_uuid": callback.operation_uuid,
                "appointment_uuid": appointment.operation_uuid,
                "campaign_code": appointment.campaign_id.code,
                "scheduled_at": fields.Datetime.to_string(appointment.scheduled_start),
                "customer_timezone": appointment.customer_timezone,
                "consent_state": appointment.consent_state,
            }
            self.env["cc.operation.outbox"]._emit(
                callback,
                "cc.callback.scheduled.v1",
                callback.middleware_idempotency_key,
                callback.correlation_id,
                payload,
                "callback_publication_disabled",
            )
            self.env["cc.reminder"]._schedule_for_appointment(appointment, callback)
        return True


class CcReminder(models.Model):
    _name = "cc.reminder"
    _description = "Campaign Reminder"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "scheduled_at, id"

    operation_uuid = fields.Char(
        string="Reminder UUID", required=True, default=lambda self: str(uuid.uuid4()),
        readonly=True, copy=False, index=True,
    )
    appointment_id = fields.Many2one("cc.appointment", ondelete="restrict", index=True)
    callback_id = fields.Many2one("cc.callback", required=True, ondelete="restrict", index=True)
    recipient_membership_id = fields.Many2one("cc.campaign.membership", required=True, ondelete="restrict")
    event_type = fields.Selection(
        [("callback_ready", "Callback Ready"), ("appointment_prep", "Appointment Preparation"), ("overdue_recovery", "Overdue Recovery")],
        required=True,
    )
    scheduled_at = fields.Datetime(required=True, index=True)
    state = fields.Selection(
        [("held", "Held"), ("acknowledged", "Acknowledged"), ("expired", "Expired")],
        required=True, default="held", readonly=True, index=True,
    )
    hold_reason = fields.Char(required=True, default="external reminder delivery disabled", readonly=True)
    idempotency_key = fields.Char(required=True, readonly=True, copy=False, index=True)
    acknowledged_at = fields.Datetime(readonly=True)

    _operation_uuid_unique = models.Constraint(
        "unique(operation_uuid)", "Reminder UUIDs must be unique."
    )
    _reminder_idempotency_unique = models.Constraint(
        "unique(idempotency_key)", "Reminder idempotency keys must be unique."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_reminder_capability") is not REMINDER_WRITE_CAPABILITY:
            raise AccessError(_("Reminders require the governed scheduler."))
        records = super().create(values_list)
        return records.with_env(records.env(context=dict(records.env.context, _cc_reminder_capability=None)))

    def write(self, values):
        if self.env.context.get("_cc_reminder_capability") is not REMINDER_WRITE_CAPABILITY:
            raise AccessError(_("Reminder state requires a governed action."))
        return super().write(values)

    def unlink(self):
        raise AccessError(_("Reminder evidence cannot be deleted."))

    @api.constrains("campaign_id", "appointment_id", "callback_id", "recipient_membership_id")
    def _check_scope(self):
        for reminder in self:
            if reminder.callback_id.campaign_id != reminder.campaign_id:
                raise ValidationError(_("Reminder and callback campaigns differ."))
            if reminder.appointment_id and reminder.appointment_id.campaign_id != reminder.campaign_id:
                raise ValidationError(_("Reminder and appointment campaigns differ."))
            if reminder.recipient_membership_id.campaign_id != reminder.campaign_id:
                raise ValidationError(_("Reminder recipient belongs to another campaign."))

    @api.model
    def _create_once(self, values):
        existing = self.search([("idempotency_key", "=", values["idempotency_key"])], limit=1)
        return existing or self.with_context(_cc_reminder_capability=REMINDER_WRITE_CAPABILITY).create(values)

    @api.model
    def _schedule_for_callback(self, callback):
        minutes = callback.policy_id.reminder_minutes
        return self._create_once(
            {
                "campaign_id": callback.campaign_id.id,
                "callback_id": callback.id,
                "recipient_membership_id": (callback.assigned_membership_id or callback.supervisor_membership_id).id,
                "event_type": "callback_ready",
                "scheduled_at": fields.Datetime.subtract(callback.scheduled_at, minutes=minutes),
                "idempotency_key": f"{callback.operation_uuid}:callback-ready:{minutes}",
            }
        )

    @api.model
    def _schedule_for_appointment(self, appointment, callback):
        minutes = appointment.policy_id.reminder_minutes
        return self._create_once(
            {
                "campaign_id": appointment.campaign_id.id,
                "appointment_id": appointment.id,
                "callback_id": callback.id,
                "recipient_membership_id": appointment.assigned_membership_id.id,
                "event_type": "appointment_prep",
                "scheduled_at": fields.Datetime.subtract(appointment.scheduled_start, minutes=minutes),
                "idempotency_key": f"{appointment.operation_uuid}:appointment-prep:{minutes}",
            }
        )

    def action_acknowledge(self):
        for reminder in self:
            _resolve_campaign(self.env, reminder.campaign_id.id, record=reminder)
            if reminder.recipient_membership_id.user_id != self.env.user and not self.env.user.has_group(
                "codestra_cc_security.group_cc_campaign_supervisor"
            ):
                raise AccessError(_("Only the recipient or campaign supervisor may acknowledge."))
            if reminder.state == "acknowledged":
                continue
            reminder.with_context(_cc_reminder_capability=REMINDER_WRITE_CAPABILITY).write(
                {"state": "acknowledged", "acknowledged_at": fields.Datetime.now()}
            )
        return True
