import hashlib
import json
import uuid

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

RESULT_APPLICATION_CAPABILITY = object()
RUN_STATE_CAPABILITY = object()
DRIFT_RESOLUTION_CAPABILITY = object()


def canonical_hash(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class CampaignMappingTelephonyProjection(models.Model):
    _inherit = "call.center.campaign.mapping"

    policy_hash = fields.Char(size=64, copy=False)
    last_result_id = fields.Many2one(
        "codestra.integration.result.inbox", ondelete="restrict", copy=False
    )
    last_reconciled_at = fields.Datetime(copy=False)


class IdentityLinkTelephonyProjection(models.Model):
    _inherit = "codestra.identity.link"

    desired_state_version = fields.Integer(default=0, required=True, copy=False)
    actual_state_version = fields.Integer(default=0, required=True, copy=False)
    desired_state_hash = fields.Char(size=64, copy=False)
    actual_state_hash = fields.Char(size=64, copy=False)
    last_result_id = fields.Many2one(
        "codestra.integration.result.inbox", ondelete="restrict", copy=False
    )

    _telephony_versions_nonnegative = models.Constraint(
        "check(desired_state_version >= 0 AND actual_state_version >= 0)",
        "Telephony state versions cannot be negative.",
    )


class ExtensionAssignmentTelephonyProjection(models.Model):
    _inherit = "codestra.extension.assignment"

    allocation_reservation_public_id = fields.Char(index=True, copy=False)
    phone_public_id = fields.Char(index=True, copy=False)
    desired_state_version = fields.Integer(default=0, required=True, copy=False)
    actual_state_version = fields.Integer(default=0, required=True, copy=False)
    last_result_id = fields.Many2one(
        "codestra.integration.result.inbox", ondelete="restrict", copy=False
    )
    last_reconciled_at = fields.Datetime(copy=False)
    reconciliation_status = fields.Selection(
        [
            ("NOT_OBSERVED", "Not Observed"),
            ("IN_SYNC", "In Sync"),
            ("DRIFTED", "Drifted"),
            ("MANUAL_REVIEW_REQUIRED", "Manual Review Required"),
        ],
        default="NOT_OBSERVED",
        required=True,
        copy=False,
    )

    _telephony_versions_nonnegative = models.Constraint(
        "check(desired_state_version >= 0 AND actual_state_version >= 0)",
        "Extension state versions cannot be negative.",
    )


class CallbackTaskTelephonyProjection(models.Model):
    _inherit = "call.center.callback.task"

    callback_public_id = fields.Char(index=True, copy=False)
    record_environment = fields.Selection(
        [("TEST", "Test"), ("STAGING", "Staging"), ("PRODUCTION", "Production")],
        default="STAGING",
        required=True,
        copy=False,
        index=True,
    )
    idempotency_key = fields.Char(index=True, copy=False)
    last_result_id = fields.Many2one(
        "codestra.integration.result.inbox", ondelete="restrict", copy=False
    )
    reconciliation_status = fields.Selection(
        [
            ("NOT_OBSERVED", "Not Observed"),
            ("IN_SYNC", "In Sync"),
            ("DRIFTED", "Drifted"),
            ("MANUAL_REVIEW_REQUIRED", "Manual Review Required"),
        ],
        default="NOT_OBSERVED",
        required=True,
        copy=False,
    )

    _callback_public_id_unique = models.Constraint(
        "unique(record_environment, callback_public_id)",
        "Callback public IDs must be unique within an environment.",
    )
    _callback_idempotency_unique = models.Constraint(
        "unique(record_environment, idempotency_key)",
        "Callback idempotency keys must be unique within an environment.",
    )


class TelephonyDesiredState(models.Model):
    _name = "codestra.telephony.desired.state"
    _description = "Odoo Telephony Desired and Observed State"
    _inherit = ["mail.thread", "call.center.business.unit.mixin"]  # noqa: RUF012
    _order = "employee_id, campaign_id"

    state_public_id = fields.Char(
        required=True, default=lambda self: str(uuid.uuid4()), copy=False, index=True
    )
    record_environment = fields.Selection(
        [("TEST", "Test"), ("STAGING", "Staging"), ("PRODUCTION", "Production")],
        default="STAGING",
        required=True,
        copy=False,
        index=True,
    )
    employee_id = fields.Many2one(
        "hr.employee", required=True, ondelete="restrict", index=True
    )
    agent_public_id = fields.Char(
        related="employee_id.codestra_employee_number",
        string="Agent Public ID",
        store=True,
        index=True,
    )
    business_unit_public_id = fields.Char(
        related="business_unit_id.code",
        string="Business Unit Public ID",
        store=True,
        index=True,
    )
    campaign_id = fields.Many2one(
        "call.center.campaign", required=True, ondelete="restrict", index=True
    )
    campaign_public_id = fields.Char(
        related="campaign_id.code",
        string="Campaign Public ID",
        store=True,
        index=True,
    )
    allocation_reservation_public_id = fields.Char(index=True, copy=False)
    identity_link_id = fields.Many2one(
        "codestra.identity.link", ondelete="restrict", index=True
    )
    extension_assignment_id = fields.Many2one(
        "codestra.extension.assignment", ondelete="restrict", index=True
    )
    phone_public_id = fields.Char(index=True, copy=False)
    endpoint_public_id = fields.Char(index=True, copy=False)
    extension = fields.Char(index=True, copy=False)
    desired_enabled = fields.Boolean(default=False, required=True)
    desired_campaign_membership = fields.Boolean(default=False, required=True)
    desired_transfer_permission = fields.Boolean(default=False, required=True)
    desired_callback_permission = fields.Boolean(default=False, required=True)
    desired_external_call_permission = fields.Boolean(default=False, required=True)
    desired_endpoint_context_key = fields.Char(copy=False)
    desired_phone_active = fields.Boolean(default=False, required=True)
    desired_user_active = fields.Boolean(default=False, required=True)
    desired_state_version = fields.Integer(default=1, required=True, copy=False)
    desired_state_hash = fields.Char(required=True, size=64, copy=False)
    desired_state_updated_at = fields.Datetime(
        default=fields.Datetime.now, required=True, copy=False
    )
    observed_state = fields.Selection(
        [
            ("NOT_OBSERVED", "Not Observed"),
            ("DISABLED", "Disabled"),
            ("ENABLED", "Enabled"),
            ("MISSING", "Missing"),
            ("AMBIGUOUS", "Ambiguous"),
        ],
        default="NOT_OBSERVED",
        required=True,
        copy=False,
        index=True,
    )
    actual_state_version = fields.Integer(default=0, required=True, copy=False)
    observed_state_version = fields.Integer(default=0, required=True, copy=False)
    observed_state_hash = fields.Char(size=64, copy=False)
    observed_vicidial_user_exists = fields.Boolean(copy=False)
    observed_vicidial_user_active = fields.Boolean(copy=False)
    observed_vicidial_phone_exists = fields.Boolean(copy=False)
    observed_vicidial_phone_active = fields.Boolean(copy=False)
    observed_asterisk_endpoint_exists = fields.Boolean(copy=False)
    observed_asterisk_endpoint_enabled = fields.Boolean(copy=False)
    observed_asterisk_contact_count = fields.Integer(default=0, copy=False)
    observed_registration_status = fields.Selection(
        [
            ("UNKNOWN", "Unknown"),
            ("UNREGISTERED", "Unregistered"),
            ("REGISTERED", "Registered"),
            ("UNAVAILABLE", "Unavailable"),
        ],
        default="UNKNOWN",
        required=True,
        copy=False,
    )
    observed_campaign_membership = fields.Boolean(copy=False)
    observed_at = fields.Datetime(copy=False)
    last_command_public_id = fields.Char(index=True, copy=False)
    last_operation_public_id = fields.Char(index=True, copy=False)
    last_adapter_operation_id = fields.Char(index=True, copy=False)
    last_result_id = fields.Many2one(
        "codestra.integration.result.inbox", ondelete="restrict", copy=False
    )
    last_readback_at = fields.Datetime(copy=False)
    last_successful_readback_at = fields.Datetime(copy=False)
    last_reconciled_at = fields.Datetime(copy=False)
    last_reconciliation_run_id = fields.Many2one(
        "codestra.integration.reconciliation.run", ondelete="restrict", copy=False
    )
    last_reconciliation_drift_id = fields.Many2one(
        "codestra.integration.reconciliation.drift", ondelete="restrict", copy=False
    )
    last_error_code = fields.Char(copy=False)
    last_error_safe_message = fields.Char(copy=False)
    reconciliation_status = fields.Selection(
        [
            ("NOT_OBSERVED", "Not Observed"),
            ("IN_SYNC", "In Sync"),
            ("DRIFTED", "Drifted"),
            ("AMBIGUOUS", "Ambiguous"),
            ("MANUAL_REVIEW_REQUIRED", "Manual Review Required"),
            ("UNKNOWN", "Unknown"),
            ("DRIFT_DETECTED", "Drift Detected"),
            ("RECONCILIATION_REQUESTED", "Reconciliation Requested"),
            ("RECONCILIATION_RUNNING", "Reconciliation Running"),
            ("REPAIR_APPROVAL_REQUIRED", "Repair Approval Required"),
            ("REPAIRING", "Repairing"),
            ("RECONCILED", "Reconciled"),
            ("FAILED", "Failed"),
        ],
        default="NOT_OBSERVED",
        required=True,
        copy=False,
        index=True,
    )

    _state_public_id_unique = models.Constraint(
        "unique(state_public_id)", "Telephony desired-state IDs must be unique."
    )
    _employee_campaign_unique = models.Constraint(
        "unique(record_environment, employee_id, campaign_id)",
        "An employee has one telephony desired state per campaign and environment.",
    )
    _state_versions_valid = models.Constraint(
        """
        check(
            desired_state_version > 0
            AND actual_state_version >= 0
            AND observed_state_version >= 0
            AND observed_asterisk_contact_count >= 0
        )
        """,
        "Telephony state versions are invalid.",
    )

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            desired = self._desired_document(values)
            expected = canonical_hash(desired)
            supplied = values.get("desired_state_hash")
            if supplied and supplied != expected:
                raise ValidationError("Desired telephony state hash is invalid.")
            values["desired_state_hash"] = expected
        return super().create(values_list)

    def write(self, values):
        desired_fields = {
            "desired_enabled",
            "desired_campaign_membership",
            "desired_transfer_permission",
            "desired_callback_permission",
            "desired_external_call_permission",
            "desired_endpoint_context_key",
            "desired_phone_active",
            "desired_user_active",
            "phone_public_id",
            "endpoint_public_id",
            "extension",
            "allocation_reservation_public_id",
        }
        observed_fields = {
            "observed_state",
            "actual_state_version",
            "observed_state_version",
            "observed_state_hash",
            "observed_vicidial_user_exists",
            "observed_vicidial_user_active",
            "observed_vicidial_phone_exists",
            "observed_vicidial_phone_active",
            "observed_asterisk_endpoint_exists",
            "observed_asterisk_endpoint_enabled",
            "observed_asterisk_contact_count",
            "observed_registration_status",
            "observed_campaign_membership",
            "observed_at",
            "last_command_public_id",
            "last_operation_public_id",
            "last_adapter_operation_id",
            "last_result_id",
            "last_readback_at",
            "last_successful_readback_at",
            "last_reconciled_at",
            "last_reconciliation_run_id",
            "last_reconciliation_drift_id",
            "reconciliation_status",
            "last_error_code",
            "last_error_safe_message",
        }
        if observed_fields.intersection(values) and (
            self.env.context.get("_codestra_telephony_result_capability")
            is not RESULT_APPLICATION_CAPABILITY
        ):
            raise AccessError("Observed telephony state is result controlled.")
        if desired_fields.intersection(values):
            for record in self:
                next_values = dict(values)
                next_values["desired_state_version"] = record.desired_state_version + 1
                next_values["desired_state_hash"] = canonical_hash(
                    record._desired_document(next_values)
                )
                next_values["desired_state_updated_at"] = fields.Datetime.now()
                super(TelephonyDesiredState, record).write(next_values)
            return True
        if "desired_state_version" in values or "desired_state_hash" in values:
            raise AccessError("Desired telephony versioning is model controlled.")
        return super().write(values)

    def unlink(self):
        raise AccessError("Telephony desired-state history cannot be deleted.")

    def _desired_document(self, values):
        record = self[:1]

        def value(name, default=False):
            if name in values:
                return values[name]
            return getattr(record, name, default) if record else default

        return {
            "desired_enabled": bool(value("desired_enabled")),
            "desired_campaign_membership": bool(
                value("desired_campaign_membership")
            ),
            "desired_transfer_permission": bool(
                value("desired_transfer_permission")
            ),
            "desired_callback_permission": bool(
                value("desired_callback_permission")
            ),
            "desired_external_call_permission": bool(
                value("desired_external_call_permission")
            ),
            "desired_endpoint_context_key": value("desired_endpoint_context_key")
            or None,
            "desired_phone_active": bool(value("desired_phone_active")),
            "desired_user_active": bool(value("desired_user_active")),
            "phone_public_id": value("phone_public_id") or None,
            "endpoint_public_id": value("endpoint_public_id") or None,
            "extension": value("extension") or None,
            "allocation_reservation_public_id": value(
                "allocation_reservation_public_id"
            )
            or None,
        }

    def apply_observed_result(
        self,
        *,
        result,
        observed_state,
        actual_state_version,
        observed_state_hash,
        adapter_operation_id,
        observed_values=None,
    ):
        self.ensure_one()
        if result.originating_outbox_id.campaign_id != self.campaign_id:
            raise ValidationError("Telephony result campaign binding is invalid.")
        if actual_state_version < self.actual_state_version:
            raise ValidationError("Observed telephony state version cannot decrease.")
        if observed_state not in dict(
            self._fields["observed_state"].selection
        ):
            raise ValidationError("Observed telephony state is invalid.")
        now = fields.Datetime.now()
        status = (
            "IN_SYNC"
            if actual_state_version == self.desired_state_version
            and observed_state_hash == self.desired_state_hash
            else "DRIFTED"
        )
        write_values = {
            "observed_state": observed_state,
            "actual_state_version": actual_state_version,
            "observed_state_version": actual_state_version,
            "observed_state_hash": observed_state_hash,
            "last_adapter_operation_id": adapter_operation_id,
            "last_operation_public_id": adapter_operation_id,
            "last_result_id": result.id,
            "last_readback_at": now,
            "observed_at": now,
            "last_successful_readback_at": now,
            "last_reconciled_at": now,
            "reconciliation_status": status,
        }
        allowed_observed_values = {
            "observed_vicidial_user_exists",
            "observed_vicidial_user_active",
            "observed_vicidial_phone_exists",
            "observed_vicidial_phone_active",
            "observed_asterisk_endpoint_exists",
            "observed_asterisk_endpoint_enabled",
            "observed_asterisk_contact_count",
            "observed_registration_status",
            "observed_campaign_membership",
        }
        supplied = observed_values or {}
        if set(supplied) - allowed_observed_values:
            raise ValidationError("Unsupported observed telephony readback field.")
        write_values.update(supplied)
        return self.with_context(
            _codestra_telephony_result_capability=RESULT_APPLICATION_CAPABILITY
        ).write(write_values)

    @api.constrains(
        "business_unit_id", "campaign_id", "identity_link_id",
        "extension_assignment_id", "extension"
    )
    def _check_scope_and_mapping(self):
        for record in self:
            if record.campaign_id.business_unit_id != record.business_unit_id:
                raise ValidationError("Telephony campaign is outside the business unit.")
            if record.identity_link_id and (
                record.identity_link_id.employee_id != record.employee_id
                or record.identity_link_id.business_unit_id != record.business_unit_id
                or record.identity_link_id.system != "sip"
            ):
                raise ValidationError("Telephony identity link binding is invalid.")
            if record.extension_assignment_id and (
                record.extension_assignment_id.employee_id != record.employee_id
                or record.extension_assignment_id.extension != record.extension
            ):
                raise ValidationError("Telephony extension binding is invalid.")


class TelephonyTransferRequest(models.Model):
    _name = "codestra.telephony.transfer.request"
    _description = "Odoo Telephony Transfer Business Request"
    _inherit = ["mail.thread", "call.center.business.unit.mixin"]  # noqa: RUF012
    _order = "create_date desc"

    transfer_public_id = fields.Char(
        required=True, default=lambda self: str(uuid.uuid4()), copy=False, index=True
    )
    record_environment = fields.Selection(
        [("TEST", "Test"), ("STAGING", "Staging"), ("PRODUCTION", "Production")],
        default="STAGING",
        required=True,
        copy=False,
        index=True,
    )
    lead_id = fields.Many2one("crm.lead", required=True, ondelete="restrict")
    lead_public_id = fields.Char(
        related="lead_id.integration_uuid",
        string="Lead Public ID",
        store=True,
        index=True,
    )
    campaign_id = fields.Many2one(
        "call.center.campaign", required=True, ondelete="restrict"
    )
    source_campaign_public_id = fields.Char(
        related="campaign_id.code",
        string="Source Campaign Public ID",
        store=True,
        index=True,
    )
    requested_by_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user
    )
    call_public_id = fields.Char(required=True, index=True, copy=False)
    source_agent_id = fields.Many2one("res.users", ondelete="restrict", index=True)
    source_agent_public_id = fields.Char(copy=False, index=True)
    destination_agent_id = fields.Many2one(
        "res.users", ondelete="restrict", index=True
    )
    destination_agent_public_id = fields.Char(copy=False, index=True)
    destination_campaign_id = fields.Many2one(
        "call.center.campaign", ondelete="restrict", index=True
    )
    destination_campaign_public_id = fields.Char(
        related="destination_campaign_id.code",
        string="Destination Campaign Public ID",
        store=True,
        index=True,
    )
    transfer_type = fields.Selection(
        [
            ("BLIND", "Blind"),
            ("ATTENDED", "Attended"),
            ("QUEUE", "Queue"),
        ],
        required=True,
        default="ATTENDED",
    )
    source_extension = fields.Char(required=True, copy=False)
    target_classification = fields.Selection(
        [("INTERNAL_EXTENSION", "Internal Extension"), ("QUEUE", "Queue")],
        required=True,
    )
    target_reference = fields.Char(required=True, copy=False)
    attempt_count = fields.Integer(default=0, required=True, copy=False)
    correlation_id = fields.Char(required=True, index=True, copy=False)
    causation_id = fields.Char(index=True, copy=False)
    idempotency_key = fields.Char(required=True, index=True, copy=False)
    policy_hash = fields.Char(size=64, copy=False)
    state = fields.Selection(
        [
            ("REQUESTED", "Requested"),
            ("VALIDATING", "Validating"),
            ("REJECTED", "Rejected"),
            ("WAITING_FOR_DESTINATION", "Waiting for Destination"),
            ("DESTINATION_CONTACTED", "Destination Contacted"),
            ("DESTINATION_ACCEPTED", "Destination Accepted"),
            ("CONNECTING", "Connecting"),
            ("CONNECTED", "Connected"),
            ("CALLBACK_REQUIRED", "Callback Required"),
            ("EXPIRED", "Expired"),
            ("POLICY_PENDING", "Policy Pending"),
            ("DENIED", "Denied"),
            ("APPROVED", "Approved"),
            ("DISPATCH_DISABLED", "Dispatch Disabled"),
            ("COMPLETED", "Completed"),
            ("CANCELLED", "Cancelled"),
            ("FAILED", "Failed"),
        ],
        default="REQUESTED",
        required=True,
        copy=False,
        tracking=True,
    )
    last_result_id = fields.Many2one(
        "codestra.integration.result.inbox", ondelete="restrict", copy=False
    )
    requested_at = fields.Datetime(default=fields.Datetime.now, required=True)
    validated_at = fields.Datetime(copy=False)
    destination_contacted_at = fields.Datetime(copy=False)
    connected_at = fields.Datetime(copy=False)
    completed_at = fields.Datetime(copy=False)
    safe_failure_code = fields.Char(copy=False)
    failure_safe_message = fields.Char(copy=False)
    callback_task_id = fields.Many2one(
        "call.center.callback.task", ondelete="restrict", copy=False
    )
    transition_ids = fields.One2many(
        "codestra.telephony.transfer.transition",
        "transfer_request_id",
        readonly=True,
    )

    _transfer_public_id_unique = models.Constraint(
        "unique(record_environment, transfer_public_id)",
        "Transfer public IDs must be unique within an environment.",
    )
    _transfer_idempotency_unique = models.Constraint(
        "unique(record_environment, idempotency_key)",
        "Transfer idempotency keys must be unique within an environment.",
    )
    _transfer_attempt_count_nonnegative = models.Constraint(
        "check(attempt_count >= 0)", "Transfer attempt count cannot be negative."
    )

    @api.model_create_multi
    def create(self, values_list):
        if any(values.get("state", "REQUESTED") != "REQUESTED" for values in values_list):
            raise ValidationError("Transfer requests must start in REQUESTED.")
        records = self.browse()
        immutable = {
            "lead_id",
            "campaign_id",
            "call_public_id",
            "source_agent_id",
            "destination_agent_id",
            "destination_campaign_id",
            "transfer_type",
            "target_classification",
            "target_reference",
            "correlation_id",
        }
        transition_model = self.env["codestra.telephony.transfer.transition"]
        for values in values_list:
            environment = values.get("record_environment", "STAGING")
            existing = self.search(
                [
                    ("record_environment", "=", environment),
                    ("idempotency_key", "=", values["idempotency_key"]),
                ],
                limit=1,
            )
            if existing:
                conflict = any(
                    field in values
                    and (
                        getattr(existing, field).id
                        if existing._fields[field].type == "many2one"
                        else getattr(existing, field)
                    )
                    != values[field]
                    for field in immutable
                )
                if conflict:
                    raise ValidationError("IMMUTABLE_TRANSFER_BINDING_CONFLICT")
                records |= existing
                continue
            record = super().create(values)
            records |= record
            transition_model.create(
                {
                    "transfer_request_id": record.id,
                    "from_state": False,
                    "to_state": "REQUESTED",
                    "occurred_at": record.requested_at,
                    "correlation_id": record.correlation_id,
                    "safe_summary": "Transfer requested.",
                }
            )
        return records

    def write(self, values):
        transitions = {
            "REQUESTED": {"VALIDATING", "POLICY_PENDING", "CANCELLED", "EXPIRED"},
            "VALIDATING": {
                "REJECTED",
                "WAITING_FOR_DESTINATION",
                "CONNECTING",
                "CANCELLED",
                "EXPIRED",
            },
            "REJECTED": set(),
            "WAITING_FOR_DESTINATION": {
                "DESTINATION_CONTACTED",
                "FAILED",
                "CANCELLED",
                "EXPIRED",
            },
            "DESTINATION_CONTACTED": {
                "DESTINATION_ACCEPTED",
                "FAILED",
                "CANCELLED",
                "EXPIRED",
            },
            "DESTINATION_ACCEPTED": {"CONNECTING", "FAILED", "CANCELLED"},
            "CONNECTING": {"CONNECTED", "FAILED", "CANCELLED"},
            "CONNECTED": {"COMPLETED", "FAILED"},
            "CALLBACK_REQUIRED": {"COMPLETED", "CANCELLED"},
            "EXPIRED": set(),
            "POLICY_PENDING": {"DENIED", "APPROVED", "CANCELLED"},
            "APPROVED": {
                "DISPATCH_DISABLED",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
            },
            "DISPATCH_DISABLED": set(),
            "DENIED": set(),
            "COMPLETED": set(),
            "CANCELLED": set(),
            "FAILED": {"CALLBACK_REQUIRED"},
        }
        if "state" in values:
            for record in self:
                if values["state"] not in transitions[record.state]:
                    raise ValidationError(
                        f"Invalid transfer transition {record.state} -> "
                        f"{values['state']}."
                    )
        previous = {record.id: record.state for record in self}
        transition_values = dict(values)
        next_state = transition_values.get("state")
        now = fields.Datetime.now()
        if next_state == "VALIDATING":
            transition_values.setdefault("validated_at", now)
        elif next_state == "DESTINATION_CONTACTED":
            transition_values.setdefault("destination_contacted_at", now)
        elif next_state == "CONNECTED":
            transition_values.setdefault("connected_at", now)
        elif next_state == "COMPLETED":
            transition_values.setdefault("completed_at", now)
        if next_state in {"WAITING_FOR_DESTINATION", "CONNECTING"}:
            for record in self:
                values_for_record = dict(
                    transition_values, attempt_count=record.attempt_count + 1
                )
                super(TelephonyTransferRequest, record).write(values_for_record)
            result = True
        else:
            result = super().write(transition_values)
        if "state" in values:
            transition_model = self.env["codestra.telephony.transfer.transition"]
            for record in self:
                transition_model.create(
                    {
                        "transfer_request_id": record.id,
                        "from_state": previous[record.id],
                        "to_state": record.state,
                        "occurred_at": fields.Datetime.now(),
                        "correlation_id": record.correlation_id,
                        "safe_summary": values.get("failure_safe_message")
                        or f"Transfer entered {record.state}.",
                    }
                )
        return result

    def unlink(self):
        raise AccessError("Transfer request history cannot be deleted.")

    @api.constrains(
        "business_unit_id", "lead_id", "campaign_id", "destination_campaign_id"
    )
    def _check_scope(self):
        for record in self:
            if (
                record.lead_id.business_unit_id != record.business_unit_id
                or record.campaign_id.business_unit_id != record.business_unit_id
                or (
                    record.destination_campaign_id
                    and record.destination_campaign_id.business_unit_id
                    != record.business_unit_id
                )
            ):
                raise ValidationError("Transfer request scope is invalid.")


class TelephonyTransferTransition(models.Model):
    _name = "codestra.telephony.transfer.transition"
    _description = "Immutable Telephony Transfer Transition"
    _order = "occurred_at, id"

    transition_public_id = fields.Char(
        required=True, default=lambda self: str(uuid.uuid4()), copy=False, index=True
    )
    transfer_request_id = fields.Many2one(
        "codestra.telephony.transfer.request",
        required=True,
        ondelete="restrict",
        index=True,
    )
    from_state = fields.Char(copy=False)
    to_state = fields.Char(required=True, copy=False)
    occurred_at = fields.Datetime(
        required=True, default=fields.Datetime.now, copy=False
    )
    correlation_id = fields.Char(required=True, index=True, copy=False)
    safe_summary = fields.Char(copy=False)

    _transition_public_id_unique = models.Constraint(
        "unique(transition_public_id)", "Transfer transition IDs must be unique."
    )

    def write(self, values):
        raise AccessError("Transfer transitions are immutable.")

    def unlink(self):
        raise AccessError("Transfer transitions cannot be deleted.")


class IntegrationReconciliationRun(models.Model):
    _name = "codestra.integration.reconciliation.run"
    _description = "Integration Reconciliation Run Projection"
    _order = "started_at desc, id desc"

    run_public_id = fields.Char(
        required=True, default=lambda self: str(uuid.uuid4()), copy=False, index=True
    )
    environment = fields.Selection(
        [("TEST", "Test"), ("STAGING", "Staging"), ("PRODUCTION", "Production")],
        required=True,
        copy=False,
        index=True,
    )
    scope_type = fields.Selection(
        [
            ("GLOBAL", "Global"),
            ("ORGANIZATION", "Organization"),
            ("BUSINESS_UNIT", "Business Unit"),
            ("CAMPAIGN", "Campaign"),
            ("AGGREGATE", "Aggregate"),
        ],
        required=True,
    )
    organization_public_id = fields.Char(index=True)
    business_unit_id = fields.Many2one(
        "call.center.business.unit", ondelete="restrict", index=True
    )
    campaign_id = fields.Many2one(
        "call.center.campaign", ondelete="restrict", index=True
    )
    aggregate_model = fields.Char(index=True)
    aggregate_public_id = fields.Char(index=True)
    target_system = fields.Char(required=True, index=True)
    trigger_type = fields.Selection(
        [("SCHEDULED", "Scheduled"), ("ON_DEMAND", "On Demand")], required=True
    )
    triggered_by = fields.Char(required=True)
    status = fields.Selection(
        [
            ("REQUESTED", "Requested"),
            ("RUNNING", "Running"),
            ("COMPLETED", "Completed"),
            ("COMPLETED_WITH_DRIFT", "Completed With Drift"),
            ("FAILED", "Failed"),
            ("CANCELLED", "Cancelled"),
        ],
        default="REQUESTED",
        required=True,
        copy=False,
        index=True,
    )
    started_at = fields.Datetime(required=True, default=fields.Datetime.now)
    completed_at = fields.Datetime(copy=False)
    records_scanned = fields.Integer(default=0, required=True)
    records_in_sync = fields.Integer(default=0, required=True)
    drift_count = fields.Integer(default=0, required=True)
    repairable_count = fields.Integer(default=0, required=True)
    manual_review_count = fields.Integer(default=0, required=True)
    failed_count = fields.Integer(default=0, required=True)
    cursor = fields.Char(copy=False)
    configuration_version = fields.Char(required=True)
    policy_hash = fields.Char(required=True, size=64)
    evidence_checksum = fields.Char(size=64, copy=False)
    scan_idempotency_key = fields.Char(index=True, copy=False)
    last_error_code = fields.Char(copy=False)
    last_error_safe_message = fields.Char(copy=False)
    drift_ids = fields.One2many(
        "codestra.integration.reconciliation.drift",
        "reconciliation_run_id",
        readonly=True,
    )

    _run_public_id_unique = models.Constraint(
        "unique(run_public_id)", "Reconciliation run IDs must be unique."
    )
    _run_scan_idempotency_unique = models.Constraint(
        "unique(scan_idempotency_key)",
        "Reconciliation scans must be idempotent.",
    )
    _run_counts_nonnegative = models.Constraint(
        """
        check(
            records_scanned >= 0 AND records_in_sync >= 0
            AND drift_count >= 0 AND repairable_count >= 0
            AND manual_review_count >= 0 AND failed_count >= 0
        )
        """,
        "Reconciliation counters cannot be negative.",
    )

    @api.model_create_multi
    def create(self, values_list):
        if any(values.get("status", "REQUESTED") != "REQUESTED" for values in values_list):
            raise ValidationError("Reconciliation runs must start in REQUESTED.")
        return super().create(values_list)

    def write(self, values):
        controlled = {
            "status",
            "completed_at",
            "records_scanned",
            "records_in_sync",
            "drift_count",
            "repairable_count",
            "manual_review_count",
            "failed_count",
            "cursor",
            "evidence_checksum",
            "last_error_code",
            "last_error_safe_message",
        }
        if controlled.intersection(values) and (
            self.env.context.get("_codestra_reconciliation_capability")
            is not RUN_STATE_CAPABILITY
        ):
            raise AccessError("Reconciliation run state is middleware controlled.")
        transitions = {
            "REQUESTED": {"RUNNING", "CANCELLED"},
            "RUNNING": {
                "COMPLETED",
                "COMPLETED_WITH_DRIFT",
                "FAILED",
                "CANCELLED",
            },
            "COMPLETED": set(),
            "COMPLETED_WITH_DRIFT": set(),
            "FAILED": set(),
            "CANCELLED": set(),
        }
        if "status" in values:
            for record in self:
                if values["status"] not in transitions[record.status]:
                    raise ValidationError(
                        f"Invalid reconciliation transition {record.status} -> "
                        f"{values['status']}."
                    )
        return super().write(values)

    def unlink(self):
        raise AccessError("Reconciliation run evidence cannot be deleted.")

    @api.model
    def get_or_create_scan(self, values):
        key = values.get("scan_idempotency_key")
        existing = (
            self.search([("scan_idempotency_key", "=", key)], limit=1)
            if key
            else self.browse()
        )
        return existing or self.create(values)


class IntegrationReconciliationDrift(models.Model):
    _name = "codestra.integration.reconciliation.drift"
    _description = "Immutable Integration Reconciliation Drift"
    _order = "detected_at desc, id desc"

    drift_public_id = fields.Char(
        required=True, default=lambda self: str(uuid.uuid4()), copy=False, index=True
    )
    reconciliation_run_id = fields.Many2one(
        "codestra.integration.reconciliation.run",
        required=True,
        ondelete="restrict",
        index=True,
    )
    aggregate_model = fields.Char(required=True, index=True)
    aggregate_public_id = fields.Char(required=True, index=True)
    source_system = fields.Char(required=True)
    target_system = fields.Char(required=True, index=True)
    target_resource_type = fields.Char(required=True)
    target_public_id = fields.Char(required=True, index=True)
    drift_type = fields.Selection(
        [
            ("MISSING_TARGET", "Missing Target"),
            ("MISSING_SOURCE", "Missing Source"),
            ("DUPLICATE_TARGET", "Duplicate Target"),
            ("IDENTITY_MISMATCH", "Identity Mismatch"),
            ("VERSION_MISMATCH", "Version Mismatch"),
            ("STATE_MISMATCH", "State Mismatch"),
            ("POLICY_MISMATCH", "Policy Mismatch"),
            ("RESULT_MISSING", "Result Missing"),
            ("ACKNOWLEDGEMENT_MISSING", "Acknowledgement Missing"),
            ("STALE_MAPPING", "Stale Mapping"),
            ("ORPHAN_MAPPING", "Orphan Mapping"),
            ("AMBIGUOUS", "Ambiguous"),
        ],
        required=True,
        index=True,
    )
    severity = fields.Selection(
        [("INFO", "Info"), ("WARNING", "Warning"), ("ERROR", "Error"), ("CRITICAL", "Critical")],
        required=True,
    )
    expected_state_version = fields.Integer(default=0, required=True)
    observed_state_version = fields.Integer(default=0, required=True)
    expected_state_hash = fields.Char(size=64)
    observed_state_hash = fields.Char(size=64)
    expected_state_redacted = fields.Json()
    observed_state_redacted = fields.Json()
    repair_eligibility = fields.Selection(
        [
            ("SAFE_AUTOMATIC", "Safe Automatic"),
            ("APPROVAL_REQUIRED", "Approval Required"),
            ("MANUAL_ONLY", "Manual Only"),
            ("NOT_REPAIRABLE", "Not Repairable"),
        ],
        required=True,
    )
    repair_status = fields.Selection(
        [
            ("NOT_REQUESTED", "Not Requested"),
            ("REQUESTED", "Requested"),
            ("APPROVED", "Approved"),
            ("DENIED", "Denied"),
            ("COMPLETED", "Completed"),
            ("FAILED", "Failed"),
        ],
        default="NOT_REQUESTED",
        required=True,
        copy=False,
    )
    detected_at = fields.Datetime(required=True, default=fields.Datetime.now)
    acknowledged_at = fields.Datetime(copy=False)
    resolved_at = fields.Datetime(copy=False)
    resolution_result_id = fields.Many2one(
        "codestra.integration.result.inbox", ondelete="restrict"
    )
    projection_id = fields.Many2one(
        "codestra.telephony.desired.state", ondelete="restrict", index=True
    )
    mapping_id = fields.Many2one(
        "codestra.telephony.target.mapping", ondelete="restrict", index=True
    )
    employee_id = fields.Many2one("hr.employee", ondelete="restrict", index=True)
    campaign_id = fields.Many2one(
        "call.center.campaign", ondelete="restrict", index=True
    )
    command_public_id = fields.Char(index=True)
    trace_id = fields.Many2one(
        "codestra.integration.trace", ondelete="restrict", index=True
    )
    resolution_summary = fields.Char(copy=False)

    _drift_public_id_unique = models.Constraint(
        "unique(drift_public_id)", "Reconciliation drift IDs must be unique."
    )
    _drift_binding_unique = models.Constraint(
        """
        unique(
            reconciliation_run_id, aggregate_model, aggregate_public_id,
            target_system, target_resource_type, target_public_id, drift_type
        )
        """,
        "A reconciliation run may record an identical drift once.",
    )
    _drift_versions_nonnegative = models.Constraint(
        "check(expected_state_version >= 0 AND observed_state_version >= 0)",
        "Reconciliation state versions cannot be negative.",
    )

    @api.model_create_multi
    def create(self, values_list):
        if any(
            values.get("repair_status", "NOT_REQUESTED") != "NOT_REQUESTED"
            for values in values_list
        ):
            raise ValidationError("Drift repair projection must start in NOT_REQUESTED.")
        return super().create(values_list)

    def write(self, values):
        allowed = {
            "repair_status",
            "acknowledged_at",
            "resolved_at",
            "resolution_result_id",
            "resolution_summary",
        }
        if set(values) - allowed:
            raise AccessError("Reconciliation drift evidence is immutable.")
        transitions = {
            "NOT_REQUESTED": {"REQUESTED"},
            "REQUESTED": {"APPROVED", "DENIED"},
            "APPROVED": {"COMPLETED", "FAILED"},
            "DENIED": set(),
            "COMPLETED": set(),
            "FAILED": set(),
        }
        if "repair_status" in values:
            for record in self:
                verified_resolution = (
                    self.env.context.get("_codestra_drift_resolution_capability")
                    is DRIFT_RESOLUTION_CAPABILITY
                    and record.repair_status == "NOT_REQUESTED"
                    and values["repair_status"] == "COMPLETED"
                )
                if (
                    not verified_resolution
                    and values["repair_status"]
                    not in transitions[record.repair_status]
                ):
                    raise ValidationError(
                        f"Invalid repair transition {record.repair_status} -> "
                        f"{values['repair_status']}."
                    )
        return super().write(values)

    def unlink(self):
        raise AccessError("Reconciliation drift evidence cannot be deleted.")

    def _resolve_from_verified_readback(self, result, summary):
        return self.with_context(
            _codestra_drift_resolution_capability=DRIFT_RESOLUTION_CAPABILITY
        ).write(
            {
                "repair_status": "COMPLETED",
                "resolved_at": fields.Datetime.now(),
                "resolution_result_id": result.id,
                "resolution_summary": summary,
            }
        )
