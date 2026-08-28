import hashlib
import json
import math
import uuid

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


POLICY_CAPABILITY = object()
FORECAST_CAPABILITY = object()
SCHEDULE_CAPABILITY = object()
ADHERENCE_CAPABILITY = object()
EXCEPTION_CAPABILITY = object()
EXCEPTION_EVENT_CAPABILITY = object()
SNAPSHOT_CAPABILITY = object()


def _digest(value):
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_global_admin(user):
    return user.has_group("codestra_cc_security.group_cc_global_administrator")


def _is_configuration_manager(user):
    return user.has_group(
        "codestra_cc_security.group_cc_campaign_configuration_manager"
    )


def _is_wfm(user):
    return user.has_group("codestra_cc_security.group_cc_workforce_analyst")


def _is_supervisor(user):
    return user.has_group("codestra_cc_security.group_cc_campaign_supervisor")


def _is_event_service(user):
    return user.has_group("codestra_cc_wfm.group_cc_workforce_event_service")


def _membership(env, campaign, role, user=None):
    user = user or env.user
    membership = env["cc.campaign.membership"].search(
        [
            ("user_id", "=", user.id),
            ("campaign_id", "=", campaign.id),
            ("role", "=", role),
            ("state", "=", "active"),
        ],
        limit=1,
    )
    if not membership:
        raise AccessError(
            _("An active %(role)s membership is required for this campaign.", role=role)
        )
    return membership


class CcWorkforcePolicy(models.Model):
    _name = "cc.workforce.policy"
    _description = "Versioned Campaign Workforce Policy"
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
    source_reference = fields.Char(required=True, readonly=True)
    interval_minutes = fields.Selection(
        [("15", "15 Minutes"), ("30", "30 Minutes"), ("60", "60 Minutes")],
        required=True,
        default="30",
    )
    asa_target_seconds = fields.Float(required=True, default=20.0)
    abandon_target_percent = fields.Float(required=True, default=3.0)
    occupancy_min_percent = fields.Float(required=True, default=85.0)
    occupancy_max_percent = fields.Float(required=True, default=92.0)
    adherence_target_percent = fields.Float(required=True, default=90.0)
    transfer_success_target_percent = fields.Float(required=True, default=80.0)
    callback_sla_minutes = fields.Integer(required=True, default=120)
    fcr_target_percent = fields.Float(required=True, default=70.0)
    quality_target_percent = fields.Float(required=True, default=85.0)
    late_tolerance_minutes = fields.Integer(required=True, default=5)
    extended_break_tolerance_minutes = fields.Integer(required=True, default=5)
    author_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict"
    )
    approver_id = fields.Many2one(
        "res.users", readonly=True, copy=False, ondelete="restrict"
    )
    approved_at = fields.Datetime(readonly=True, copy=False)
    activated_at = fields.Datetime(readonly=True, copy=False)
    policy_hash = fields.Char(size=64, readonly=True, copy=False, index=True)
    forecast_ids = fields.One2many(
        "cc.workforce.forecast", "policy_id", readonly=True
    )

    _campaign_version_unique = models.Constraint(
        "unique(campaign_id, version)",
        "Workforce-policy versions must be unique per campaign.",
    )

    def _payload(self):
        self.ensure_one()
        return {
            "campaign": self.campaign_id.code,
            "version": self.version,
            "source_reference": self.source_reference,
            "interval_minutes": self.interval_minutes,
            "asa_target_seconds": self.asa_target_seconds,
            "abandon_target_percent": self.abandon_target_percent,
            "occupancy_range": [
                self.occupancy_min_percent,
                self.occupancy_max_percent,
            ],
            "adherence_target_percent": self.adherence_target_percent,
            "transfer_success_target_percent": self.transfer_success_target_percent,
            "callback_sla_minutes": self.callback_sla_minutes,
            "fcr_target_percent": self.fcr_target_percent,
            "quality_target_percent": self.quality_target_percent,
            "late_tolerance_minutes": self.late_tolerance_minutes,
            "extended_break_tolerance_minutes": self.extended_break_tolerance_minutes,
        }

    @api.model_create_multi
    def create(self, values_list):
        if not (_is_global_admin(self.env.user) or _is_configuration_manager(self.env.user)):
            raise AccessError(_("Only campaign configuration may draft workforce policy."))
        prepared = []
        for original in values_list:
            values = dict(original)
            if values.get("state", "draft") != "draft":
                raise ValidationError(_("Workforce policy must be created in draft."))
            values["author_id"] = self.env.user.id
            prepared.append(values)
        return super().create(prepared)

    def write(self, values):
        internal = self.env.context.get("_cc_wfm_policy_capability") is POLICY_CAPABILITY
        content = {
            "campaign_id",
            "name",
            "version",
            "source_reference",
            "interval_minutes",
            "asa_target_seconds",
            "abandon_target_percent",
            "occupancy_min_percent",
            "occupancy_max_percent",
            "adherence_target_percent",
            "transfer_success_target_percent",
            "callback_sla_minutes",
            "fcr_target_percent",
            "quality_target_percent",
            "late_tolerance_minutes",
            "extended_break_tolerance_minutes",
        }
        if not internal and ("state" in values or any(row.state != "draft" for row in self)):
            raise AccessError(_("Approved workforce policy is immutable."))
        if not internal and content.intersection(values) and not (
            _is_global_admin(self.env.user) or _is_configuration_manager(self.env.user)
        ):
            raise AccessError(_("Only campaign configuration may edit draft policy."))
        return super().write(values)

    def unlink(self):
        if any(row.state != "draft" for row in self):
            raise AccessError(_("Submitted workforce policy is retained as evidence."))
        return super().unlink()

    @api.constrains(
        "asa_target_seconds",
        "abandon_target_percent",
        "occupancy_min_percent",
        "occupancy_max_percent",
        "adherence_target_percent",
        "callback_sla_minutes",
        "late_tolerance_minutes",
    )
    def _check_targets(self):
        for policy in self:
            percentages = [
                policy.abandon_target_percent,
                policy.occupancy_min_percent,
                policy.occupancy_max_percent,
                policy.adherence_target_percent,
                policy.transfer_success_target_percent,
                policy.fcr_target_percent,
                policy.quality_target_percent,
            ]
            if any(value < 0 or value > 100 for value in percentages):
                raise ValidationError(_("Workforce percentage targets must be 0 to 100."))
            if policy.occupancy_min_percent > policy.occupancy_max_percent:
                raise ValidationError(_("Occupancy minimum cannot exceed maximum."))
            if policy.asa_target_seconds <= 0 or policy.callback_sla_minutes <= 0:
                raise ValidationError(_("Service-time targets must be positive."))
            if policy.late_tolerance_minutes < 0:
                raise ValidationError(_("Adherence tolerances cannot be negative."))

    def action_submit(self):
        for policy in self:
            if policy.state != "draft" or policy.author_id != self.env.user:
                raise AccessError(_("Only the author may submit draft workforce policy."))
            policy.with_context(_cc_wfm_policy_capability=POLICY_CAPABILITY).write(
                {"state": "submitted", "policy_hash": _digest(policy._payload())}
            )
        return True

    def action_approve(self):
        if not _is_global_admin(self.env.user):
            raise AccessError(_("Global contact-center approval is required."))
        for policy in self:
            if policy.state != "submitted":
                raise ValidationError(_("Only submitted workforce policy may be approved."))
            if policy.author_id == self.env.user:
                raise ValidationError(_("The policy author cannot approve the same version."))
            if policy.policy_hash != _digest(policy._payload()):
                raise ValidationError(_("Workforce policy changed after submission."))
            policy.with_context(_cc_wfm_policy_capability=POLICY_CAPABILITY).write(
                {
                    "state": "approved",
                    "approver_id": self.env.user.id,
                    "approved_at": fields.Datetime.now(),
                }
            )
        return True

    def action_activate(self):
        if not _is_global_admin(self.env.user):
            raise AccessError(_("Global contact-center activation is required."))
        for policy in self:
            if policy.state != "approved" or not policy.policy_hash:
                raise ValidationError(_("Only approved workforce policy may be activated."))
            active = self.search(
                [
                    ("campaign_id", "=", policy.campaign_id.id),
                    ("state", "=", "active"),
                    ("id", "!=", policy.id),
                ],
                limit=1,
            )
            if active:
                raise ValidationError(_("A campaign already has an active workforce policy."))
            policy.with_context(_cc_wfm_policy_capability=POLICY_CAPABILITY).write(
                {"state": "active", "activated_at": fields.Datetime.now()}
            )
        return True

    def action_retire(self):
        if not _is_global_admin(self.env.user):
            raise AccessError(_("Global contact-center retirement is required."))
        self.with_context(_cc_wfm_policy_capability=POLICY_CAPABILITY).write(
            {"state": "retired"}
        )
        return True


class CcWorkforceForecast(models.Model):
    _name = "cc.workforce.forecast"
    _description = "Campaign Workforce Interval Forecast"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "interval_start desc, id desc"

    reference = fields.Char(
        required=True, default=lambda self: str(uuid.uuid4()), readonly=True, copy=False
    )
    policy_id = fields.Many2one(
        "cc.workforce.policy", required=True, readonly=True, ondelete="restrict"
    )
    interval_start = fields.Datetime(required=True, readonly=True, index=True)
    interval_end = fields.Datetime(required=True, readonly=True, index=True)
    channel_type = fields.Selection(
        [("voice", "Voice"), ("email", "Email"), ("ticket", "Ticket"), ("callback", "Callback")],
        required=True,
        readonly=True,
    )
    skill_code = fields.Char(required=True, readonly=True)
    expected_contacts = fields.Integer(required=True, readonly=True)
    expected_aht_seconds = fields.Float(required=True, readonly=True)
    shrinkage_percent = fields.Float(required=True, readonly=True)
    required_staff = fields.Integer(required=True, readonly=True)
    state = fields.Selection(
        [("draft", "Draft"), ("finalized", "Finalized")],
        required=True,
        default="draft",
        readonly=True,
    )
    forecast_hash = fields.Char(size=64, readonly=True, copy=False)
    finalized_at = fields.Datetime(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_wfm_forecast_capability") is not FORECAST_CAPABILITY:
            raise AccessError(_("Forecasts require the governed WFM workflow."))
        records = super().create(values_list)
        records._check_scope()
        return records.with_context(_cc_wfm_forecast_capability=None)

    def write(self, values):
        if self.env.context.get("_cc_wfm_forecast_capability") is not FORECAST_CAPABILITY:
            raise AccessError(_("Forecast evidence requires the governed WFM workflow."))
        return super().write(values)

    def unlink(self):
        raise AccessError(_("Workforce forecasts are retained as versioned evidence."))

    @api.constrains("campaign_id", "policy_id", "interval_start", "interval_end")
    def _check_scope(self):
        for forecast in self:
            if forecast.policy_id.campaign_id != forecast.campaign_id:
                raise ValidationError(_("Forecast policy belongs to another campaign."))
            if forecast.interval_end <= forecast.interval_start:
                raise ValidationError(_("Forecast interval end must be after start."))
            if forecast.expected_contacts < 0 or forecast.expected_aht_seconds < 0:
                raise ValidationError(_("Forecast workload cannot be negative."))
            if forecast.shrinkage_percent < 0 or forecast.shrinkage_percent >= 100:
                raise ValidationError(_("Forecast shrinkage must be between 0 and 100."))

    @api.model
    def create_forecast(
        self,
        policy,
        interval_start,
        interval_end,
        channel_type,
        skill_code,
        expected_contacts,
        expected_aht_seconds,
        shrinkage_percent,
    ):
        policy.ensure_one()
        if not (_is_wfm(self.env.user) or _is_global_admin(self.env.user)):
            raise AccessError(_("Only WFM may create an interval forecast."))
        if _is_wfm(self.env.user) and not _is_global_admin(self.env.user):
            _membership(self.env, policy.campaign_id, "workforce")
        if policy.state != "active":
            raise ValidationError(_("Forecasts require the active campaign policy."))
        start = fields.Datetime.to_datetime(interval_start)
        end = fields.Datetime.to_datetime(interval_end)
        interval_seconds = (end - start).total_seconds()
        if interval_seconds <= 0:
            raise ValidationError(_("Forecast interval must be positive."))
        productive_fraction = 1.0 - (float(shrinkage_percent) / 100.0)
        occupancy_fraction = policy.occupancy_max_percent / 100.0
        capacity = interval_seconds * productive_fraction * occupancy_fraction
        workload = int(expected_contacts) * float(expected_aht_seconds)
        required_staff = math.ceil(workload / capacity) if workload and capacity else 0
        return self.with_context(_cc_wfm_forecast_capability=FORECAST_CAPABILITY).create(
            {
                "campaign_id": policy.campaign_id.id,
                "policy_id": policy.id,
                "interval_start": start,
                "interval_end": end,
                "channel_type": channel_type,
                "skill_code": str(skill_code or "").strip()[:64],
                "expected_contacts": int(expected_contacts),
                "expected_aht_seconds": float(expected_aht_seconds),
                "shrinkage_percent": float(shrinkage_percent),
                "required_staff": required_staff,
            }
        )

    def action_finalize(self):
        for forecast in self:
            if forecast.state != "draft":
                raise ValidationError(_("Only draft forecasts may be finalized."))
            if not (_is_wfm(self.env.user) or _is_global_admin(self.env.user)):
                raise AccessError(_("Only WFM may finalize a forecast."))
            if _is_wfm(self.env.user) and not _is_global_admin(self.env.user):
                _membership(self.env, forecast.campaign_id, "workforce")
            payload = {
                "reference": forecast.reference,
                "policy_hash": forecast.policy_id.policy_hash,
                "interval": [forecast.interval_start, forecast.interval_end],
                "channel_type": forecast.channel_type,
                "skill_code": forecast.skill_code,
                "workload": [forecast.expected_contacts, forecast.expected_aht_seconds],
                "shrinkage": forecast.shrinkage_percent,
                "required_staff": forecast.required_staff,
            }
            forecast.with_context(_cc_wfm_forecast_capability=FORECAST_CAPABILITY).write(
                {
                    "state": "finalized",
                    "forecast_hash": _digest(payload),
                    "finalized_at": fields.Datetime.now(),
                }
            )
        return True


class CcWorkforceSchedule(models.Model):
    _name = "cc.workforce.schedule"
    _description = "Campaign Agent Schedule"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "start_at desc, id desc"

    reference = fields.Char(
        required=True, default=lambda self: str(uuid.uuid4()), readonly=True, copy=False
    )
    policy_id = fields.Many2one(
        "cc.workforce.policy", required=True, readonly=True, ondelete="restrict"
    )
    agent_membership_id = fields.Many2one(
        "cc.campaign.membership", required=True, readonly=True, ondelete="restrict", index=True
    )
    start_at = fields.Datetime(required=True, readonly=True, index=True)
    end_at = fields.Datetime(required=True, readonly=True, index=True)
    timezone = fields.Char(required=True, readonly=True, default="UTC")
    activity_type = fields.Selection(
        [
            ("shift", "Shift"),
            ("break", "Break"),
            ("meeting", "Meeting"),
            ("training", "Training"),
            ("shrinkage", "Shrinkage"),
            ("overtime", "Overtime"),
        ],
        required=True,
        readonly=True,
        index=True,
    )
    break_minutes = fields.Integer(required=True, default=0, readonly=True)
    planned_minutes = fields.Integer(required=True, readonly=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("published", "Published"),
            ("acknowledged", "Acknowledged"),
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="draft",
        readonly=True,
        index=True,
    )
    schedule_hash = fields.Char(size=64, readonly=True, copy=False)
    published_at = fields.Datetime(readonly=True, copy=False)
    acknowledged_at = fields.Datetime(readonly=True, copy=False)
    completed_at = fields.Datetime(readonly=True, copy=False)
    adherence_event_ids = fields.One2many(
        "cc.workforce.adherence.event", "schedule_id", readonly=True
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_wfm_schedule_capability") is not SCHEDULE_CAPABILITY:
            raise AccessError(_("Schedules require the governed WFM workflow."))
        records = super().create(values_list)
        records._check_scope()
        return records.with_context(_cc_wfm_schedule_capability=None)

    def write(self, values):
        if self.env.context.get("_cc_wfm_schedule_capability") is not SCHEDULE_CAPABILITY:
            raise AccessError(_("Schedule lifecycle requires a governed action."))
        return super().write(values)

    def unlink(self):
        raise AccessError(_("Published scheduling evidence cannot be deleted."))

    @api.constrains(
        "campaign_id", "policy_id", "agent_membership_id", "start_at", "end_at", "break_minutes"
    )
    def _check_scope(self):
        for schedule in self:
            member = schedule.agent_membership_id
            if schedule.policy_id.campaign_id != schedule.campaign_id:
                raise ValidationError(_("Schedule policy belongs to another campaign."))
            if member.campaign_id != schedule.campaign_id or member.role not in {
                "agent",
                "senior_agent",
            }:
                raise ValidationError(_("Schedule agent must belong to the same campaign."))
            if member.state != "active":
                raise ValidationError(_("Schedule agent membership must be active."))
            if schedule.end_at <= schedule.start_at:
                raise ValidationError(_("Schedule end must be after start."))
            total_minutes = int((schedule.end_at - schedule.start_at).total_seconds() / 60)
            if schedule.break_minutes < 0 or schedule.break_minutes >= total_minutes:
                raise ValidationError(_("Schedule break must fit inside the interval."))
            if schedule.planned_minutes != total_minutes - schedule.break_minutes:
                raise ValidationError(_("Schedule planned minutes do not match the interval."))

    @api.model
    def create_schedule(
        self,
        policy,
        agent_membership,
        start_at,
        end_at,
        activity_type="shift",
        break_minutes=0,
        timezone="UTC",
    ):
        policy.ensure_one()
        agent_membership.ensure_one()
        if not (
            _is_wfm(self.env.user)
            or _is_supervisor(self.env.user)
            or _is_global_admin(self.env.user)
        ):
            raise AccessError(_("Only WFM or the campaign supervisor may schedule work."))
        if _is_wfm(self.env.user) and not _is_global_admin(self.env.user):
            _membership(self.env, policy.campaign_id, "workforce")
        elif _is_supervisor(self.env.user) and not _is_global_admin(self.env.user):
            _membership(self.env, policy.campaign_id, "supervisor")
        if policy.state != "active":
            raise ValidationError(_("Schedules require the active workforce policy."))
        start = fields.Datetime.to_datetime(start_at)
        end = fields.Datetime.to_datetime(end_at)
        total_minutes = int((end - start).total_seconds() / 60)
        return self.with_context(_cc_wfm_schedule_capability=SCHEDULE_CAPABILITY).create(
            {
                "campaign_id": policy.campaign_id.id,
                "policy_id": policy.id,
                "agent_membership_id": agent_membership.id,
                "start_at": start,
                "end_at": end,
                "activity_type": activity_type,
                "break_minutes": int(break_minutes),
                "planned_minutes": total_minutes - int(break_minutes),
                "timezone": str(timezone or "UTC")[:64],
            }
        )

    def action_publish(self):
        for schedule in self:
            if schedule.state != "draft":
                raise ValidationError(_("Only draft schedules may be published."))
            if not (
                _is_wfm(self.env.user)
                or _is_supervisor(self.env.user)
                or _is_global_admin(self.env.user)
            ):
                raise AccessError(_("Only WFM or the campaign supervisor may publish."))
            payload = {
                "reference": schedule.reference,
                "policy_hash": schedule.policy_id.policy_hash,
                "agent_membership": schedule.agent_membership_id.membership_uuid,
                "interval": [schedule.start_at, schedule.end_at],
                "activity_type": schedule.activity_type,
                "break_minutes": schedule.break_minutes,
                "planned_minutes": schedule.planned_minutes,
                "timezone": schedule.timezone,
            }
            schedule.with_context(_cc_wfm_schedule_capability=SCHEDULE_CAPABILITY).write(
                {
                    "state": "published",
                    "schedule_hash": _digest(payload),
                    "published_at": fields.Datetime.now(),
                }
            )
        return True

    def action_acknowledge(self):
        for schedule in self:
            if schedule.state != "published":
                raise ValidationError(_("Only a published schedule may be acknowledged."))
            if schedule.agent_membership_id.user_id != self.env.user:
                raise AccessError(_("Only the scheduled agent may acknowledge."))
            schedule.with_context(_cc_wfm_schedule_capability=SCHEDULE_CAPABILITY).write(
                {"state": "acknowledged", "acknowledged_at": fields.Datetime.now()}
            )
        return True

    def action_complete(self):
        for schedule in self:
            if schedule.state not in {"published", "acknowledged"}:
                raise ValidationError(_("Only a published schedule may be completed."))
            if not (
                _is_wfm(self.env.user)
                or _is_supervisor(self.env.user)
                or _is_global_admin(self.env.user)
            ):
                raise AccessError(_("Only WFM or the campaign supervisor may complete."))
            schedule.with_context(_cc_wfm_schedule_capability=SCHEDULE_CAPABILITY).write(
                {"state": "completed", "completed_at": fields.Datetime.now()}
            )
        return True


class CcWorkforceAdherenceEvent(models.Model):
    _name = "cc.workforce.adherence.event"
    _description = "Normalized Campaign Adherence Event"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "occurred_start desc, id desc"

    event_uuid = fields.Char(required=True, readonly=True, copy=False, index=True)
    schedule_id = fields.Many2one(
        "cc.workforce.schedule", required=True, readonly=True, ondelete="restrict"
    )
    agent_membership_id = fields.Many2one(
        "cc.campaign.membership", required=True, readonly=True, ondelete="restrict", index=True
    )
    normalized_state = fields.Selection(
        [
            ("ready", "Ready"),
            ("talk", "Talk"),
            ("hold", "Hold"),
            ("acw", "After Call Work"),
            ("pause", "Pause"),
            ("meeting", "Meeting"),
            ("training", "Training"),
            ("offline", "Offline"),
        ],
        required=True,
        readonly=True,
    )
    occurred_start = fields.Datetime(required=True, readonly=True, index=True)
    occurred_end = fields.Datetime(required=True, readonly=True, index=True)
    duration_seconds = fields.Integer(required=True, readonly=True)
    classification = fields.Selection(
        [
            ("adhering", "Adhering"),
            ("late", "Late"),
            ("absent", "Absent"),
            ("extended_break", "Extended Break"),
            ("unexpected_state", "Unexpected State"),
        ],
        required=True,
        readonly=True,
        index=True,
    )
    variance_seconds = fields.Integer(required=True, readonly=True)
    source_reference_hash = fields.Char(required=True, size=64, readonly=True)
    source_payload_hash = fields.Char(required=True, size=64, readonly=True)
    binding_hash = fields.Char(required=True, size=64, readonly=True)
    received_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True
    )
    exception_id = fields.One2many(
        "cc.workforce.exception", "adherence_event_id", readonly=True
    )

    _event_uuid_unique = models.Constraint(
        "unique(event_uuid)", "Adherence event UUIDs must be unique."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_wfm_adherence_capability") is not ADHERENCE_CAPABILITY:
            raise AccessError(_("Adherence evidence requires the governed event service."))
        records = super().create(values_list)
        records._check_scope()
        return records.with_context(_cc_wfm_adherence_capability=None)

    def write(self, values):
        raise AccessError(_("Adherence evidence is immutable."))

    def unlink(self):
        raise AccessError(_("Adherence evidence cannot be deleted."))

    @api.constrains("campaign_id", "schedule_id", "agent_membership_id")
    def _check_scope(self):
        for event in self:
            if event.schedule_id.campaign_id != event.campaign_id:
                raise ValidationError(_("Adherence schedule belongs to another campaign."))
            if event.agent_membership_id != event.schedule_id.agent_membership_id:
                raise ValidationError(_("Adherence agent does not match the schedule."))
            if event.occurred_end <= event.occurred_start:
                raise ValidationError(_("Adherence interval must be positive."))

    @api.model
    def ingest_event(
        self,
        *,
        event_uuid,
        schedule_id,
        agent_membership_id,
        normalized_state,
        occurred_start,
        occurred_end,
        source_reference,
        source_payload_hash,
    ):
        if not _is_event_service(self.env.user):
            raise AccessError(_("Only the private workforce event service may ingest state."))
        event_uuid = str(event_uuid or "").strip()
        source_reference = str(source_reference or "").strip()
        if not event_uuid or not source_reference:
            raise ValidationError(_("Event UUID and source reference are required."))
        if len(str(source_payload_hash or "")) != 64:
            raise ValidationError(_("A SHA-256 source payload hash is required."))
        schedule = self.env["cc.workforce.schedule"].browse(schedule_id).exists()
        agent = self.env["cc.campaign.membership"].browse(agent_membership_id).exists()
        if not schedule or not agent or agent != schedule.agent_membership_id:
            raise ValidationError(_("Adherence event binding is invalid."))
        start = fields.Datetime.to_datetime(occurred_start)
        end = fields.Datetime.to_datetime(occurred_end)
        duration = int((end - start).total_seconds())
        policy = schedule.policy_id
        late_seconds = max(0, int((start - schedule.start_at).total_seconds()))
        classification = "adhering"
        variance = 0
        expected_states = {
            "shift": {"ready", "talk", "hold", "acw"},
            "overtime": {"ready", "talk", "hold", "acw"},
            "break": {"pause"},
            "meeting": {"meeting"},
            "training": {"training"},
            "shrinkage": {"pause", "meeting", "training"},
        }
        if normalized_state == "offline":
            classification = "absent"
            variance = duration
        elif late_seconds > policy.late_tolerance_minutes * 60:
            classification = "late"
            variance = late_seconds
        elif normalized_state not in expected_states[schedule.activity_type]:
            classification = "unexpected_state"
            variance = duration
        elif schedule.activity_type == "break" and duration > (
            schedule.planned_minutes + policy.extended_break_tolerance_minutes
        ) * 60:
            classification = "extended_break"
            variance = duration - (schedule.planned_minutes * 60)
        payload = {
            "event_uuid": event_uuid,
            "campaign": schedule.campaign_id.code,
            "schedule": schedule.reference,
            "agent_membership": agent.membership_uuid,
            "state": normalized_state,
            "interval": [start, end],
            "source_reference_hash": hashlib.sha256(
                source_reference.encode("utf-8")
            ).hexdigest(),
            "source_payload_hash": source_payload_hash,
        }
        binding_hash = _digest(payload)
        existing = self.search([("event_uuid", "=", event_uuid)], limit=1)
        if existing:
            if existing.binding_hash != binding_hash:
                raise ValidationError(_("Altered replay of an adherence event was rejected."))
            return existing
        event = self.with_context(_cc_wfm_adherence_capability=ADHERENCE_CAPABILITY).create(
            {
                "campaign_id": schedule.campaign_id.id,
                "event_uuid": event_uuid,
                "schedule_id": schedule.id,
                "agent_membership_id": agent.id,
                "normalized_state": normalized_state,
                "occurred_start": start,
                "occurred_end": end,
                "duration_seconds": duration,
                "classification": classification,
                "variance_seconds": variance,
                "source_reference_hash": payload["source_reference_hash"],
                "source_payload_hash": source_payload_hash,
                "binding_hash": binding_hash,
            }
        )
        if classification != "adhering":
            self.env["cc.workforce.exception"]._open_from_event(event)
        return event


class CcWorkforceException(models.Model):
    _name = "cc.workforce.exception"
    _description = "Campaign Workforce Exception"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "opened_at desc, id desc"

    reference = fields.Char(
        required=True, default=lambda self: str(uuid.uuid4()), readonly=True, copy=False
    )
    adherence_event_id = fields.Many2one(
        "cc.workforce.adherence.event",
        required=True,
        readonly=True,
        ondelete="restrict",
        index=True,
    )
    agent_membership_id = fields.Many2one(
        related="adherence_event_id.agent_membership_id",
        store=True,
        readonly=True,
        index=True,
    )
    exception_type = fields.Selection(
        related="adherence_event_id.classification", store=True, readonly=True
    )
    state = fields.Selection(
        [("open", "Open"), ("acknowledged", "Acknowledged"), ("resolved", "Resolved")],
        required=True,
        default="open",
        readonly=True,
        index=True,
    )
    supervisor_membership_id = fields.Many2one(
        "cc.campaign.membership", readonly=True, ondelete="restrict"
    )
    opened_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True
    )
    acknowledged_at = fields.Datetime(readonly=True)
    resolved_at = fields.Datetime(readonly=True)
    event_ids = fields.One2many(
        "cc.workforce.exception.event", "exception_id", readonly=True
    )

    _one_exception_per_event = models.Constraint(
        "unique(adherence_event_id)", "An adherence event may open only one exception."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_wfm_exception_capability") is not EXCEPTION_CAPABILITY:
            raise AccessError(_("Workforce exceptions require normalized adherence evidence."))
        return super().create(values_list).with_context(_cc_wfm_exception_capability=None)

    def write(self, values):
        if self.env.context.get("_cc_wfm_exception_capability") is not EXCEPTION_CAPABILITY:
            raise AccessError(_("Workforce exception lifecycle requires a governed action."))
        return super().write(values)

    def unlink(self):
        raise AccessError(_("Workforce exceptions are retained as evidence."))

    @api.model
    def _open_from_event(self, event):
        event.ensure_one()
        exception = self.with_context(_cc_wfm_exception_capability=EXCEPTION_CAPABILITY).create(
            {
                "campaign_id": event.campaign_id.id,
                "adherence_event_id": event.id,
            }
        )
        self.env["cc.workforce.exception.event"]._append(
            exception, "opened", event.binding_hash
        )
        return exception

    def action_acknowledge(self, reason_code):
        reason_code = str(reason_code or "").strip()
        if not reason_code:
            raise ValidationError(_("Exception acknowledgement requires a reason code."))
        for exception in self:
            if exception.state != "open":
                raise ValidationError(_("Only open exceptions may be acknowledged."))
            supervisor = _membership(self.env, exception.campaign_id, "supervisor")
            if not supervisor.is_primary_supervisor:
                raise AccessError(_("Only the active primary supervisor may acknowledge."))
            exception.with_context(_cc_wfm_exception_capability=EXCEPTION_CAPABILITY).write(
                {
                    "state": "acknowledged",
                    "supervisor_membership_id": supervisor.id,
                    "acknowledged_at": fields.Datetime.now(),
                }
            )
            self.env["cc.workforce.exception.event"]._append(
                exception, "acknowledged", _digest(reason_code)
            )
        return True

    def action_resolve(self, resolution):
        resolution = str(resolution or "").strip()
        if not resolution:
            raise ValidationError(_("Exception resolution evidence is required."))
        for exception in self:
            if exception.state != "acknowledged":
                raise ValidationError(_("Only acknowledged exceptions may be resolved."))
            supervisor = _membership(self.env, exception.campaign_id, "supervisor")
            if supervisor != exception.supervisor_membership_id:
                raise AccessError(_("The acknowledging supervisor must resolve the exception."))
            exception.with_context(_cc_wfm_exception_capability=EXCEPTION_CAPABILITY).write(
                {"state": "resolved", "resolved_at": fields.Datetime.now()}
            )
            self.env["cc.workforce.exception.event"]._append(
                exception, "resolved", _digest(resolution)
            )
        return True


class CcWorkforceExceptionEvent(models.Model):
    _name = "cc.workforce.exception.event"
    _description = "Append-Only Workforce Exception Timeline"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "occurred_at, id"

    event_uuid = fields.Char(
        required=True, default=lambda self: str(uuid.uuid4()), readonly=True, copy=False
    )
    exception_id = fields.Many2one(
        "cc.workforce.exception", required=True, readonly=True, ondelete="restrict"
    )
    actor_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict"
    )
    event_type = fields.Selection(
        [("opened", "Opened"), ("acknowledged", "Acknowledged"), ("resolved", "Resolved")],
        required=True,
        readonly=True,
    )
    evidence_hash = fields.Char(required=True, size=64, readonly=True)
    occurred_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_wfm_exception_event_capability") is not EXCEPTION_EVENT_CAPABILITY:
            raise AccessError(_("Workforce exception timeline is append-only."))
        return super().create(values_list).with_context(
            _cc_wfm_exception_event_capability=None
        )

    def write(self, values):
        raise AccessError(_("Workforce exception timeline is immutable."))

    def unlink(self):
        raise AccessError(_("Workforce exception timeline cannot be deleted."))

    @api.model
    def _append(self, exception, event_type, evidence_hash):
        exception.ensure_one()
        return self.with_context(
            _cc_wfm_exception_event_capability=EXCEPTION_EVENT_CAPABILITY
        ).create(
            {
                "campaign_id": exception.campaign_id.id,
                "exception_id": exception.id,
                "actor_id": self.env.user.id,
                "event_type": event_type,
                "evidence_hash": evidence_hash,
            }
        )


class CcWorkforceRealtimeSnapshot(models.Model):
    _name = "cc.workforce.realtime.snapshot"
    _description = "Privacy-Minimized Campaign Real-Time Snapshot"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "interval_end desc, id desc"

    event_uuid = fields.Char(required=True, readonly=True, copy=False, index=True)
    policy_id = fields.Many2one(
        "cc.workforce.policy", required=True, readonly=True, ondelete="restrict"
    )
    interval_start = fields.Datetime(required=True, readonly=True, index=True)
    interval_end = fields.Datetime(required=True, readonly=True, index=True)
    offered = fields.Integer(required=True, readonly=True)
    answered = fields.Integer(required=True, readonly=True)
    abandoned = fields.Integer(required=True, readonly=True)
    answer_wait_seconds = fields.Integer(required=True, readonly=True)
    ready_seconds = fields.Integer(required=True, readonly=True)
    talk_seconds = fields.Integer(required=True, readonly=True)
    hold_seconds = fields.Integer(required=True, readonly=True)
    acw_seconds = fields.Integer(required=True, readonly=True)
    scheduled_staff = fields.Integer(required=True, readonly=True)
    actual_staff = fields.Integer(required=True, readonly=True)
    callback_backlog = fields.Integer(required=True, readonly=True)
    email_backlog = fields.Integer(required=True, readonly=True)
    ticket_backlog = fields.Integer(required=True, readonly=True)
    asa_seconds = fields.Float(required=True, readonly=True)
    abandon_percent = fields.Float(required=True, readonly=True)
    occupancy_percent = fields.Float(required=True, readonly=True)
    staffing_variance = fields.Integer(required=True, readonly=True)
    alert_tier = fields.Selection(
        [("normal", "Normal"), ("warning", "Warning"), ("critical", "Critical")],
        required=True,
        readonly=True,
        index=True,
    )
    integration_health = fields.Selection(
        [("healthy", "Healthy"), ("degraded", "Degraded"), ("unavailable", "Unavailable")],
        required=True,
        readonly=True,
    )
    source_payload_hash = fields.Char(required=True, size=64, readonly=True)
    binding_hash = fields.Char(required=True, size=64, readonly=True)
    received_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True
    )

    _event_uuid_unique = models.Constraint(
        "unique(event_uuid)", "Real-time snapshot event UUIDs must be unique."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_wfm_snapshot_capability") is not SNAPSHOT_CAPABILITY:
            raise AccessError(_("Real-time snapshots require the private event service."))
        records = super().create(values_list)
        records._check_scope()
        return records.with_context(_cc_wfm_snapshot_capability=None)

    def write(self, values):
        raise AccessError(_("Real-time workforce snapshots are immutable."))

    def unlink(self):
        raise AccessError(_("Real-time workforce snapshots cannot be deleted."))

    @api.constrains("campaign_id", "policy_id", "interval_start", "interval_end")
    def _check_scope(self):
        for snapshot in self:
            if snapshot.policy_id.campaign_id != snapshot.campaign_id:
                raise ValidationError(_("Snapshot policy belongs to another campaign."))
            if snapshot.interval_end <= snapshot.interval_start:
                raise ValidationError(_("Snapshot interval must be positive."))

    @api.model
    def ingest_snapshot(
        self,
        *,
        event_uuid,
        policy_id,
        interval_start,
        interval_end,
        metrics,
        integration_health,
        source_payload_hash,
    ):
        if not _is_event_service(self.env.user):
            raise AccessError(_("Only the private workforce event service may ingest metrics."))
        policy = self.env["cc.workforce.policy"].browse(policy_id).exists()
        if not policy or policy.state != "active":
            raise ValidationError(_("Real-time snapshots require active workforce policy."))
        event_uuid = str(event_uuid or "").strip()
        if not event_uuid or len(str(source_payload_hash or "")) != 64:
            raise ValidationError(_("Snapshot UUID and SHA-256 source hash are required."))
        required = {
            "offered",
            "answered",
            "abandoned",
            "answer_wait_seconds",
            "ready_seconds",
            "talk_seconds",
            "hold_seconds",
            "acw_seconds",
            "scheduled_staff",
            "actual_staff",
            "callback_backlog",
            "email_backlog",
            "ticket_backlog",
        }
        if set(metrics) != required or any(int(metrics[key]) < 0 for key in required):
            raise ValidationError(_("Real-time metric schema is incomplete or negative."))
        clean = {key: int(metrics[key]) for key in sorted(required)}
        asa = clean["answer_wait_seconds"] / clean["answered"] if clean["answered"] else 0.0
        abandon = (clean["abandoned"] / clean["offered"] * 100) if clean["offered"] else 0.0
        handled = clean["talk_seconds"] + clean["hold_seconds"] + clean["acw_seconds"]
        staffed = handled + clean["ready_seconds"]
        occupancy = handled / staffed * 100 if staffed else 0.0
        breaches = sum(
            [
                asa > policy.asa_target_seconds,
                abandon > policy.abandon_target_percent,
                occupancy < policy.occupancy_min_percent,
                occupancy > policy.occupancy_max_percent,
                integration_health != "healthy",
            ]
        )
        alert_tier = "critical" if breaches >= 2 else "warning" if breaches else "normal"
        start = fields.Datetime.to_datetime(interval_start)
        end = fields.Datetime.to_datetime(interval_end)
        payload = {
            "event_uuid": event_uuid,
            "campaign": policy.campaign_id.code,
            "policy_hash": policy.policy_hash,
            "interval": [start, end],
            "metrics": clean,
            "integration_health": integration_health,
            "source_payload_hash": source_payload_hash,
        }
        binding_hash = _digest(payload)
        existing = self.search([("event_uuid", "=", event_uuid)], limit=1)
        if existing:
            if existing.binding_hash != binding_hash:
                raise ValidationError(_("Altered replay of a real-time snapshot was rejected."))
            return existing
        return self.with_context(_cc_wfm_snapshot_capability=SNAPSHOT_CAPABILITY).create(
            {
                "campaign_id": policy.campaign_id.id,
                "event_uuid": event_uuid,
                "policy_id": policy.id,
                "interval_start": start,
                "interval_end": end,
                **clean,
                "asa_seconds": round(asa, 2),
                "abandon_percent": round(abandon, 2),
                "occupancy_percent": round(occupancy, 2),
                "staffing_variance": clean["actual_staff"] - clean["scheduled_staff"],
                "alert_tier": alert_tier,
                "integration_health": integration_health,
                "source_payload_hash": source_payload_hash,
                "binding_hash": binding_hash,
            }
        )
