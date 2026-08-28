import hashlib
import json
import uuid
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


REPORTING_POLICY_CAPABILITY = object()
KPI_SNAPSHOT_CAPABILITY = object()
EXPORT_EVENT_CAPABILITY = object()

ALLOWED_METRICS = {
    "inbound": {
        "offered",
        "answered",
        "service_level",
        "asa",
        "abandon",
        "queue_time",
        "hold",
        "aht",
        "transfer",
        "fcr",
    },
    "outbound": {
        "attempts",
        "connect",
        "contact",
        "qualified",
        "conversion",
        "callback",
        "dnc",
        "drop",
        "abandon",
        "pacing_guardrail",
    },
    "email_helpdesk": {
        "new",
        "backlog",
        "first_response",
        "resolution",
        "sla_breach",
        "reopen",
        "csat",
    },
    "agent": {
        "login",
        "ready",
        "talk",
        "hold",
        "acw",
        "pause",
        "occupancy",
        "adherence",
        "attendance",
    },
    "quality": {
        "sample_rate",
        "score",
        "critical_fail",
        "calibration_variance",
        "dispute",
        "coaching_completion",
    },
    "compliance": {
        "consent_coverage",
        "dnc_capture",
        "suppression_latency",
        "calling_hours_block",
        "disclosure_completion",
        "holds",
    },
    "integration": {
        "event_lag",
        "retries",
        "dead_letters",
        "reconciliation_drift",
        "readback_mismatch",
        "duplicate_suppression",
    },
    "workforce": {
        "forecast_accuracy",
        "staffing_variance",
        "schedule_adherence",
        "occupancy",
        "exception_backlog",
    },
}


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


def _is_reporting_service(user):
    return user.has_group("codestra_cc_wfm.group_cc_workforce_event_service")


class CcReportingPolicy(models.Model):
    _name = "cc.reporting.policy"
    _description = "Versioned Campaign Reporting Policy"
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
    pii_masking_required = fields.Boolean(required=True, default=True, readonly=True)
    supervisor_bulk_export_allowed = fields.Boolean(
        required=True, default=False, readonly=True
    )
    export_expiry_minutes = fields.Integer(required=True, default=60, readonly=True)
    author_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict"
    )
    approver_id = fields.Many2one(
        "res.users", readonly=True, copy=False, ondelete="restrict"
    )
    approved_at = fields.Datetime(readonly=True, copy=False)
    activated_at = fields.Datetime(readonly=True, copy=False)
    policy_hash = fields.Char(size=64, readonly=True, copy=False, index=True)
    definition_ids = fields.One2many(
        "cc.kpi.definition", "policy_id", readonly=True
    )

    _campaign_version_unique = models.Constraint(
        "unique(campaign_id, version)",
        "Reporting-policy versions must be unique per campaign.",
    )

    def _payload(self):
        self.ensure_one()
        return {
            "campaign": self.campaign_id.code,
            "version": self.version,
            "source_reference": self.source_reference,
            "pii_masking_required": self.pii_masking_required,
            "supervisor_bulk_export_allowed": self.supervisor_bulk_export_allowed,
            "export_expiry_minutes": self.export_expiry_minutes,
            "definitions": [
                row._payload()
                for row in self.definition_ids.sorted(
                    key=lambda definition: (definition.family, definition.metric_code)
                )
            ],
        }

    @api.model_create_multi
    def create(self, values_list):
        if not (_is_global_admin(self.env.user) or _is_configuration_manager(self.env.user)):
            raise AccessError(_("Only campaign configuration may draft reporting policy."))
        prepared = []
        for original in values_list:
            values = dict(original)
            if values.get("state", "draft") != "draft":
                raise ValidationError(_("Reporting policy must be created in draft."))
            if not values.get("pii_masking_required", True):
                raise ValidationError(_("Global KPI reporting must remain PII-masked."))
            if values.get("supervisor_bulk_export_allowed", False):
                raise ValidationError(_("Supervisor bulk export must remain disabled."))
            values["author_id"] = self.env.user.id
            prepared.append(values)
        return super().create(prepared)

    def write(self, values):
        internal = (
            self.env.context.get("_cc_reporting_policy_capability")
            is REPORTING_POLICY_CAPABILITY
        )
        if not internal and ("state" in values or any(row.state != "draft" for row in self)):
            raise AccessError(_("Approved reporting policy is immutable."))
        if values.get("pii_masking_required") is False:
            raise ValidationError(_("PII masking cannot be disabled."))
        if values.get("supervisor_bulk_export_allowed") is True:
            raise ValidationError(_("Supervisor bulk export cannot be enabled."))
        return super().write(values)

    def unlink(self):
        if any(row.state != "draft" for row in self):
            raise AccessError(_("Submitted reporting policy is retained as evidence."))
        return super().unlink()

    @api.constrains("export_expiry_minutes")
    def _check_export_expiry(self):
        for policy in self:
            if policy.export_expiry_minutes < 5 or policy.export_expiry_minutes > 120:
                raise ValidationError(_("Controlled export expiry must be 5 to 120 minutes."))

    def action_submit(self):
        for policy in self:
            if policy.state != "draft" or policy.author_id != self.env.user:
                raise AccessError(_("Only the author may submit draft reporting policy."))
            if not policy.definition_ids:
                raise ValidationError(_("Reporting policy requires KPI definitions."))
            policy.with_context(
                _cc_reporting_policy_capability=REPORTING_POLICY_CAPABILITY
            ).write({"state": "submitted", "policy_hash": _digest(policy._payload())})
        return True

    def action_approve(self):
        if not _is_global_admin(self.env.user):
            raise AccessError(_("Global contact-center approval is required."))
        for policy in self:
            if policy.state != "submitted":
                raise ValidationError(_("Only submitted reporting policy may be approved."))
            if policy.author_id == self.env.user:
                raise ValidationError(_("The reporting-policy author cannot approve it."))
            if policy.policy_hash != _digest(policy._payload()):
                raise ValidationError(_("Reporting policy changed after submission."))
            policy.with_context(
                _cc_reporting_policy_capability=REPORTING_POLICY_CAPABILITY
            ).write(
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
            if policy.state != "approved":
                raise ValidationError(_("Only approved reporting policy may be activated."))
            active = self.search(
                [
                    ("campaign_id", "=", policy.campaign_id.id),
                    ("state", "=", "active"),
                    ("id", "!=", policy.id),
                ],
                limit=1,
            )
            if active:
                raise ValidationError(_("A campaign already has active reporting policy."))
            policy.with_context(
                _cc_reporting_policy_capability=REPORTING_POLICY_CAPABILITY
            ).write({"state": "active", "activated_at": fields.Datetime.now()})
        return True

    def action_retire(self):
        if not _is_global_admin(self.env.user):
            raise AccessError(_("Global contact-center retirement is required."))
        for policy in self:
            if policy.state != "active":
                raise ValidationError(_("Only active reporting policy may be retired."))
            policy.with_context(
                _cc_reporting_policy_capability=REPORTING_POLICY_CAPABILITY
            ).write({"state": "retired"})
        return True


class CcKpiDefinition(models.Model):
    _name = "cc.kpi.definition"
    _description = "Campaign KPI Definition"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "family, metric_code, id"

    policy_id = fields.Many2one(
        "cc.reporting.policy", required=True, readonly=True, ondelete="restrict"
    )
    family = fields.Selection(
        [(key, key.replace("_", " ").title()) for key in ALLOWED_METRICS],
        required=True,
        readonly=True,
        index=True,
    )
    metric_code = fields.Char(required=True, readonly=True, index=True)
    display_name = fields.Char(required=True)
    unit = fields.Selection(
        [
            ("count", "Count"),
            ("seconds", "Seconds"),
            ("minutes", "Minutes"),
            ("percent", "Percent"),
            ("score", "Score"),
        ],
        required=True,
    )
    direction = fields.Selection(
        [
            ("higher", "Higher Is Better"),
            ("lower", "Lower Is Better"),
            ("range", "Target Range"),
            ("informational", "Informational"),
        ],
        required=True,
    )
    target_value = fields.Float()
    warning_lower = fields.Float()
    warning_upper = fields.Float()
    critical_lower = fields.Float()
    critical_upper = fields.Float()
    definition_version = fields.Char(required=True, default="1.0", readonly=True)
    authoritative_source = fields.Char(required=True)

    _policy_metric_unique = models.Constraint(
        "unique(policy_id, family, metric_code)",
        "A KPI may be defined once per reporting-policy version.",
    )

    def _payload(self):
        self.ensure_one()
        return {
            "family": self.family,
            "metric_code": self.metric_code,
            "display_name": self.display_name,
            "unit": self.unit,
            "direction": self.direction,
            "target_value": self.target_value,
            "warning": [self.warning_lower, self.warning_upper],
            "critical": [self.critical_lower, self.critical_upper],
            "definition_version": self.definition_version,
            "authoritative_source": self.authoritative_source,
        }

    @api.model_create_multi
    def create(self, values_list):
        if not (_is_global_admin(self.env.user) or _is_configuration_manager(self.env.user)):
            raise AccessError(_("Only campaign configuration may define KPI metrics."))
        for values in values_list:
            policy = self.env["cc.reporting.policy"].browse(
                values.get("policy_id")
            ).exists()
            if not policy or policy.state != "draft":
                raise AccessError(_("KPI definitions require a draft reporting policy."))
            if policy.author_id != self.env.user and not _is_global_admin(self.env.user):
                raise AccessError(_("Only the reporting-policy author may define KPI metrics."))
        records = super().create(values_list)
        records._check_definition()
        return records

    def write(self, values):
        if any(row.policy_id.state != "draft" for row in self):
            raise AccessError(_("Submitted KPI definitions are immutable."))
        return super().write(values)

    def unlink(self):
        if any(row.policy_id.state != "draft" for row in self):
            raise AccessError(_("Submitted KPI definitions are retained as evidence."))
        return super().unlink()

    @api.constrains("campaign_id", "policy_id", "family", "metric_code")
    def _check_definition(self):
        for definition in self:
            if definition.policy_id.campaign_id != definition.campaign_id:
                raise ValidationError(_("KPI definition belongs to another campaign."))
            if definition.metric_code not in ALLOWED_METRICS.get(definition.family, set()):
                raise ValidationError(_("KPI code is not part of the controlled family."))


class CcKpiSnapshot(models.Model):
    _name = "cc.kpi.snapshot"
    _description = "Immutable Campaign KPI Snapshot"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "data_cutoff_at desc, id desc"

    event_uuid = fields.Char(required=True, readonly=True, copy=False, index=True)
    policy_id = fields.Many2one(
        "cc.reporting.policy", required=True, readonly=True, ondelete="restrict"
    )
    definition_id = fields.Many2one(
        "cc.kpi.definition", required=True, readonly=True, ondelete="restrict"
    )
    family = fields.Selection(related="definition_id.family", store=True, readonly=True)
    metric_code = fields.Char(related="definition_id.metric_code", store=True, readonly=True)
    agent_membership_id = fields.Many2one(
        "cc.campaign.membership", readonly=True, ondelete="restrict", index=True
    )
    period_reference = fields.Char(required=True, readonly=True, index=True)
    value = fields.Float(required=True, readonly=True)
    unit = fields.Selection(related="definition_id.unit", store=True, readonly=True)
    target_value = fields.Float(related="definition_id.target_value", store=True, readonly=True)
    result_state = fields.Selection(
        [
            ("pass", "Pass"),
            ("warning", "Warning"),
            ("critical", "Critical"),
            ("informational", "Informational"),
        ],
        required=True,
        readonly=True,
        index=True,
    )
    reconciliation_state = fields.Selection(
        [("matched", "Matched"), ("partial", "Partial"), ("blocked", "Blocked")],
        required=True,
        readonly=True,
        index=True,
    )
    data_cutoff_at = fields.Datetime(required=True, readonly=True, index=True)
    source_payload_hash = fields.Char(required=True, size=64, readonly=True)
    binding_hash = fields.Char(required=True, size=64, readonly=True)
    aggregate_only = fields.Boolean(required=True, default=False, readonly=True)
    created_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)

    _event_uuid_unique = models.Constraint(
        "unique(event_uuid)", "KPI snapshot event UUIDs must be unique."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_kpi_snapshot_capability") is not KPI_SNAPSHOT_CAPABILITY:
            raise AccessError(_("KPI snapshots require the private reporting service."))
        records = super().create(values_list)
        records._check_scope()
        return records.with_context(_cc_kpi_snapshot_capability=None)

    def write(self, values):
        raise AccessError(_("KPI snapshots are immutable."))

    def unlink(self):
        raise AccessError(_("KPI snapshots cannot be deleted."))

    def export_data(self, fields_to_export, raw_data=False):
        raise UserError(
            _("Raw KPI export is disabled; request a controlled export manifest.")
        )

    @api.constrains("campaign_id", "policy_id", "definition_id", "agent_membership_id")
    def _check_scope(self):
        for snapshot in self:
            if snapshot.policy_id.campaign_id != snapshot.campaign_id:
                raise ValidationError(_("KPI reporting policy belongs to another campaign."))
            if snapshot.definition_id.policy_id != snapshot.policy_id:
                raise ValidationError(_("KPI definition belongs to another policy version."))
            if snapshot.agent_membership_id and (
                snapshot.agent_membership_id.campaign_id != snapshot.campaign_id
                or snapshot.agent_membership_id.role not in {"agent", "senior_agent"}
            ):
                raise ValidationError(_("Agent KPI snapshot belongs to another campaign."))
            if snapshot.aggregate_only and snapshot.agent_membership_id:
                raise ValidationError(_("Aggregate KPI snapshots cannot identify an agent."))

    @api.model
    def _classify(self, definition, value):
        if definition.direction == "informational":
            return "informational"
        if definition.direction == "higher":
            if value < definition.critical_lower:
                return "critical"
            if value < definition.warning_lower:
                return "warning"
            return "pass"
        if definition.direction == "lower":
            if value > definition.critical_upper:
                return "critical"
            if value > definition.warning_upper:
                return "warning"
            return "pass"
        if value < definition.critical_lower or value > definition.critical_upper:
            return "critical"
        if value < definition.warning_lower or value > definition.warning_upper:
            return "warning"
        return "pass"

    @api.model
    def ingest_snapshot(
        self,
        *,
        event_uuid,
        policy_id,
        definition_id,
        period_reference,
        value,
        data_cutoff_at,
        source_payload_hash,
        reconciliation_state="matched",
        agent_membership_id=None,
        aggregate_only=False,
    ):
        if not _is_reporting_service(self.env.user):
            raise AccessError(_("Only the private reporting service may ingest KPI snapshots."))
        policy = self.env["cc.reporting.policy"].browse(policy_id).exists()
        definition = self.env["cc.kpi.definition"].browse(definition_id).exists()
        agent = self.env["cc.campaign.membership"].browse(agent_membership_id).exists()
        if not policy or policy.state != "active" or definition.policy_id != policy:
            raise ValidationError(_("KPI snapshot requires active policy and definition."))
        if agent and agent.campaign_id != policy.campaign_id:
            raise ValidationError(_("KPI agent belongs to another campaign."))
        if len(str(source_payload_hash or "")) != 64:
            raise ValidationError(_("A SHA-256 source payload hash is required."))
        event_uuid = str(event_uuid or "").strip()
        period_reference = str(period_reference or "").strip()
        if not event_uuid or not period_reference:
            raise ValidationError(_("KPI event UUID and period reference are required."))
        result_state = self._classify(definition, float(value))
        payload = {
            "event_uuid": event_uuid,
            "campaign": policy.campaign_id.code,
            "policy_hash": policy.policy_hash,
            "definition": definition._payload(),
            "period_reference": period_reference,
            "value": float(value),
            "data_cutoff_at": fields.Datetime.to_datetime(data_cutoff_at),
            "source_payload_hash": source_payload_hash,
            "reconciliation_state": reconciliation_state,
            "agent_membership": agent.membership_uuid if agent else None,
            "aggregate_only": bool(aggregate_only),
        }
        binding_hash = _digest(payload)
        existing = self.search([("event_uuid", "=", event_uuid)], limit=1)
        if existing:
            if existing.binding_hash != binding_hash:
                raise ValidationError(_("Altered replay of a KPI snapshot was rejected."))
            return existing
        return self.with_context(_cc_kpi_snapshot_capability=KPI_SNAPSHOT_CAPABILITY).create(
            {
                "campaign_id": policy.campaign_id.id,
                "event_uuid": event_uuid,
                "policy_id": policy.id,
                "definition_id": definition.id,
                "agent_membership_id": agent.id if agent else False,
                "period_reference": period_reference,
                "value": float(value),
                "result_state": result_state,
                "reconciliation_state": reconciliation_state,
                "data_cutoff_at": fields.Datetime.to_datetime(data_cutoff_at),
                "source_payload_hash": source_payload_hash,
                "binding_hash": binding_hash,
                "aggregate_only": bool(aggregate_only),
            }
        )

    def request_controlled_export(self, reason):
        if not _is_global_admin(self.env.user):
            raise AccessError(_("Controlled KPI export requires global administration."))
        if not self:
            raise ValidationError(_("A controlled export requires KPI snapshots."))
        campaigns = self.mapped("campaign_id")
        if len(campaigns) != 1:
            raise ValidationError(_("A controlled export must remain within one campaign."))
        reason = str(reason or "").strip()
        if not reason:
            raise ValidationError(_("Controlled export requires a reason."))
        policy = self.sorted(key=lambda row: row.id)[-1].policy_id
        checksum = _digest(sorted(self.mapped("binding_hash")))
        event = self.env["cc.reporting.export.event"]._append(
            campaign=campaigns,
            policy=policy,
            row_count=len(self),
            checksum=checksum,
            reason=reason,
        )
        return {
            "status": "manifest_only",
            "event_uuid": event.event_uuid,
            "campaign_code": campaigns.code,
            "row_count": len(self),
            "checksum": checksum,
            "expires_at": event.expires_at,
        }


class CcReportingExportEvent(models.Model):
    _name = "cc.reporting.export.event"
    _description = "Controlled Reporting Export Evidence"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "requested_at desc, id desc"

    event_uuid = fields.Char(
        required=True, default=lambda self: str(uuid.uuid4()), readonly=True, copy=False
    )
    policy_id = fields.Many2one(
        "cc.reporting.policy", required=True, readonly=True, ondelete="restrict"
    )
    requester_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict"
    )
    reason_hash = fields.Char(required=True, size=64, readonly=True)
    row_count = fields.Integer(required=True, readonly=True)
    checksum_sha256 = fields.Char(required=True, size=64, readonly=True)
    requested_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True
    )
    expires_at = fields.Datetime(required=True, readonly=True)
    delivery_state = fields.Selection(
        [("manifest_only", "Manifest Only"), ("expired", "Expired")],
        required=True,
        default="manifest_only",
        readonly=True,
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_export_event_capability") is not EXPORT_EVENT_CAPABILITY:
            raise AccessError(_("Reporting export evidence requires the governed workflow."))
        return super().create(values_list).with_context(_cc_export_event_capability=None)

    def write(self, values):
        raise AccessError(_("Reporting export evidence is immutable."))

    def unlink(self):
        raise AccessError(_("Reporting export evidence cannot be deleted."))

    @api.model
    def _append(self, campaign, policy, row_count, checksum, reason):
        return self.with_context(_cc_export_event_capability=EXPORT_EVENT_CAPABILITY).create(
            {
                "campaign_id": campaign.id,
                "policy_id": policy.id,
                "requester_id": self.env.user.id,
                "reason_hash": hashlib.sha256(reason.encode("utf-8")).hexdigest(),
                "row_count": row_count,
                "checksum_sha256": checksum,
                "expires_at": fields.Datetime.now()
                + timedelta(minutes=policy.export_expiry_minutes),
            }
        )
