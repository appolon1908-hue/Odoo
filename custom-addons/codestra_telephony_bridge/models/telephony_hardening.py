import uuid

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .telephony import RESULT_APPLICATION_CAPABILITY

MAPPING_APPLICATION_CAPABILITY = object()
TELEPHONY_RESULT_WRITE_CAPABILITY = object()


class TelephonyTargetMapping(models.Model):
    _name = "codestra.telephony.target.mapping"
    _description = "Target-Specific Telephony Mapping Projection"
    _order = "agent_public_id, campaign_public_id, target_system"

    mapping_public_id = fields.Char(
        required=True, default=lambda self: str(uuid.uuid4()), copy=False, index=True
    )
    environment = fields.Selection(
        [("TEST", "Test"), ("STAGING", "Staging"), ("PRODUCTION", "Production")],
        required=True,
        default="STAGING",
        copy=False,
        index=True,
    )
    employee_id = fields.Many2one(
        "hr.employee", required=True, ondelete="restrict", index=True
    )
    agent_public_id = fields.Char(required=True, copy=False, index=True)
    business_unit_id = fields.Many2one(
        "call.center.business.unit", required=True, ondelete="restrict", index=True
    )
    business_unit_public_id = fields.Char(required=True, copy=False, index=True)
    campaign_id = fields.Many2one(
        "call.center.campaign", required=True, ondelete="restrict", index=True
    )
    campaign_public_id = fields.Char(required=True, copy=False, index=True)
    allocation_reservation_public_id = fields.Char(index=True, copy=False)
    target_system = fields.Selection(
        [
            ("KEYCLOAK", "Keycloak"),
            ("VICIDIAL_USER", "VICIdial User"),
            ("VICIDIAL_PHONE", "VICIdial Phone"),
            ("ASTERISK_ENDPOINT", "Asterisk Endpoint"),
            ("ASTERISK_CONTACT", "Asterisk Contact"),
            ("N8N_WORKFLOW_BINDING", "n8n Workflow Binding"),
        ],
        required=True,
        copy=False,
        index=True,
    )
    target_resource_type = fields.Char(required=True, copy=False, index=True)
    target_public_id = fields.Char(required=True, copy=False, index=True)
    target_native_id = fields.Char(copy=False, index=True)
    extension = fields.Char(copy=False, index=True)
    phone_public_id = fields.Char(copy=False, index=True)
    endpoint_public_id = fields.Char(copy=False, index=True)
    vicidial_user_reference = fields.Char(copy=False, index=True)
    vicidial_phone_reference = fields.Char(copy=False, index=True)
    desired_state_version = fields.Integer(default=0, required=True, copy=False)
    observed_state_version = fields.Integer(default=0, required=True, copy=False)
    desired_state_hash = fields.Char(size=64, copy=False)
    observed_state_hash = fields.Char(size=64, copy=False)
    mapping_status = fields.Selection(
        [
            ("PROPOSED", "Proposed"),
            ("RESERVED", "Reserved"),
            ("PROVISIONING", "Provisioning"),
            ("ACTIVE", "Active"),
            ("DISABLED", "Disabled"),
            ("SUSPENDED", "Suspended"),
            ("REVOKED", "Revoked"),
            ("TERMINATED", "Terminated"),
            ("STALE", "Stale"),
            ("ORPHANED", "Orphaned"),
            ("CONFLICT", "Conflict"),
        ],
        required=True,
        default="PROPOSED",
        copy=False,
        index=True,
    )
    created_from_result_id = fields.Many2one(
        "codestra.integration.result.inbox", ondelete="restrict", copy=False
    )
    last_readback_at = fields.Datetime(copy=False)
    last_reconciled_at = fields.Datetime(copy=False)

    _mapping_public_id_unique = models.Constraint(
        "unique(mapping_public_id)", "Telephony mapping IDs must be unique."
    )
    _mapping_versions_nonnegative = models.Constraint(
        "check(desired_state_version >= 0 AND observed_state_version >= 0)",
        "Telephony mapping versions cannot be negative.",
    )

    def init(self):
        self.env.cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                codestra_telephony_target_mapping_active_resource_uniq
            ON codestra_telephony_target_mapping (
                environment, target_system, target_resource_type, target_public_id
            )
            WHERE mapping_status IN (
                'RESERVED', 'PROVISIONING', 'ACTIVE', 'DISABLED', 'SUSPENDED'
            )
            """
        )

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            self._validate_scope_values(values)
        return super().create(values_list)

    def write(self, values):
        observed_fields = {
            "observed_state_version",
            "observed_state_hash",
            "mapping_status",
            "target_native_id",
            "last_readback_at",
            "last_reconciled_at",
            "created_from_result_id",
        }
        if observed_fields.intersection(values) and (
            self.env.context.get("_codestra_mapping_application_capability")
            is not MAPPING_APPLICATION_CAPABILITY
        ):
            raise AccessError("Observed target mappings are result controlled.")
        if "mapping_status" in values:
            transitions = {
                "PROPOSED": {"RESERVED", "CONFLICT"},
                "RESERVED": {"PROVISIONING", "REVOKED", "CONFLICT"},
                "PROVISIONING": {"ACTIVE", "DISABLED", "CONFLICT"},
                "ACTIVE": {"DISABLED", "SUSPENDED", "REVOKED", "STALE", "ORPHANED"},
                "DISABLED": {"SUSPENDED", "REVOKED", "TERMINATED", "STALE"},
                "SUSPENDED": {"DISABLED", "REVOKED", "TERMINATED", "STALE"},
                "REVOKED": {"TERMINATED"},
                "TERMINATED": set(),
                "STALE": {"REVOKED", "TERMINATED"},
                "ORPHANED": {"REVOKED", "TERMINATED"},
                "CONFLICT": {"REVOKED", "TERMINATED"},
            }
            for record in self:
                if (
                    values["mapping_status"] != record.mapping_status
                    and values["mapping_status"]
                    not in transitions[record.mapping_status]
                ):
                    raise ValidationError(
                        f"Invalid mapping transition {record.mapping_status} -> "
                        f"{values['mapping_status']}."
                    )
        return super().write(values)

    def unlink(self):
        raise AccessError("Telephony target mapping evidence cannot be deleted.")

    @api.constrains(
        "employee_id",
        "agent_public_id",
        "business_unit_id",
        "business_unit_public_id",
        "campaign_id",
        "campaign_public_id",
        "extension",
        "allocation_reservation_public_id",
    )
    def _check_scope(self):
        for record in self:
            self._validate_scope_values(
                {
                    "employee_id": record.employee_id.id,
                    "agent_public_id": record.agent_public_id,
                    "business_unit_id": record.business_unit_id.id,
                    "business_unit_public_id": record.business_unit_public_id,
                    "campaign_id": record.campaign_id.id,
                    "campaign_public_id": record.campaign_public_id,
                    "extension": record.extension,
                    "allocation_reservation_public_id":
                        record.allocation_reservation_public_id,
                }
            )

    @api.model
    def _validate_scope_values(self, values):
        employee = self.env["hr.employee"].browse(values.get("employee_id"))
        unit = self.env["call.center.business.unit"].browse(
            values.get("business_unit_id")
        )
        campaign = self.env["call.center.campaign"].browse(values.get("campaign_id"))
        if employee.codestra_employee_number and (
            employee.codestra_employee_number != values.get("agent_public_id")
        ):
            raise ValidationError("Telephony mapping agent identity is invalid.")
        if unit.code != values.get("business_unit_public_id"):
            raise ValidationError("Telephony mapping business-unit identity is invalid.")
        if campaign.code != values.get("campaign_public_id"):
            raise ValidationError("Telephony mapping campaign identity is invalid.")
        if campaign.business_unit_id != unit:
            raise ValidationError("Telephony mapping campaign scope is invalid.")
        assignment = self.env["codestra.extension.assignment"].search(
            [
                ("employee_id", "=", employee.id),
                ("extension", "=", values.get("extension")),
                ("allocation_reservation_public_id", "=",
                 values.get("allocation_reservation_public_id")),
            ],
            limit=1,
        )
        if values.get("extension") and not assignment:
            raise ValidationError(
                "Telephony mapping extension allocation binding is invalid."
            )

    def _apply_readback(
        self, *, result, status, observed_state_version, observed_state_hash
    ):
        self.ensure_one()
        if result.campaign_id != self.campaign_id:
            raise ValidationError("Telephony mapping result campaign is invalid.")
        if result.source_environment.upper() != self.environment:
            raise ValidationError("Telephony mapping result environment is invalid.")
        if observed_state_version < self.observed_state_version:
            raise ValidationError("Telephony mapping observed version cannot decrease.")
        return self.with_context(
            _codestra_mapping_application_capability=MAPPING_APPLICATION_CAPABILITY
        ).write(
            {
                "mapping_status": status,
                "observed_state_version": observed_state_version,
                "observed_state_hash": observed_state_hash,
                "created_from_result_id": result.id,
                "last_readback_at": fields.Datetime.now(),
            }
        )


class IntegrationResultTelephonyProjection(models.Model):
    _inherit = "codestra.integration.result.inbox"

    result_domain = fields.Selection(
        [("GENERAL", "General"), ("TELEPHONY", "Telephony")],
        default="GENERAL",
        required=True,
        readonly=True,
    )
    command_public_id = fields.Char(index=True, readonly=True)
    operation_public_id = fields.Char(index=True, readonly=True)
    target_system = fields.Char(index=True, readonly=True)
    target_resource_type = fields.Char(readonly=True)
    target_public_id = fields.Char(index=True, readonly=True)
    command_type = fields.Char(readonly=True)
    operation_type = fields.Char(readonly=True)
    requested_state_version = fields.Integer(default=0, readonly=True)
    applied_state_version = fields.Integer(default=0, readonly=True)
    observed_state_version = fields.Integer(default=0, readonly=True)
    application_status = fields.Selection(
        [
            ("RECEIVED", "Received"),
            ("VALIDATED", "Validated"),
            ("APPLYING", "Applying"),
            ("APPLIED", "Applied"),
            ("READBACK_PENDING", "Readback Pending"),
            ("READBACK_VERIFIED", "Readback Verified"),
            ("READBACK_MISMATCH", "Readback Mismatch"),
            ("RECONCILIATION_REQUIRED", "Reconciliation Required"),
            ("STALE", "Stale"),
            ("FAILED", "Failed"),
        ],
        default="RECEIVED",
        required=True,
        readonly=True,
    )
    readback_status = fields.Char(readonly=True)
    application_hash = fields.Char(size=64, readonly=True)
    readback_hash = fields.Char(size=64, readonly=True)
    applied_at = fields.Datetime(readonly=True)
    readback_at = fields.Datetime(readonly=True)
    mapping_id = fields.Many2one(
        "codestra.telephony.target.mapping", ondelete="restrict", readonly=True
    )
    projection_id = fields.Many2one(
        "codestra.telephony.desired.state", ondelete="restrict", readonly=True
    )
    reconciliation_run_id = fields.Many2one(
        "codestra.integration.reconciliation.run", ondelete="restrict", readonly=True
    )
    reconciliation_drift_id = fields.Many2one(
        "codestra.integration.reconciliation.drift", ondelete="restrict", readonly=True
    )
    safe_result_summary = fields.Char(readonly=True)
    safe_readback_summary = fields.Char(readonly=True)

    def write(self, values):
        telephony_fields = {
            "applied_state_version",
            "observed_state_version",
            "application_status",
            "readback_status",
            "application_hash",
            "readback_hash",
            "applied_at",
            "readback_at",
            "mapping_id",
            "projection_id",
            "reconciliation_run_id",
            "reconciliation_drift_id",
            "safe_result_summary",
            "safe_readback_summary",
        }
        if telephony_fields.intersection(values):
            if (
                self.env.context.get("_codestra_telephony_result_write_capability")
                is not TELEPHONY_RESULT_WRITE_CAPABILITY
            ):
                raise AccessError("Telephony result application is service controlled.")
            return models.Model.write(self, values)
        return super().write(values)

    def _apply_telephony_readback(
        self,
        *,
        projection,
        mapping,
        reconciliation_run,
        observed_state,
        observed_state_version,
        observed_state_hash,
        mapping_status,
        application_hash,
        safe_summary,
        observed_values=None,
    ):
        self.ensure_one()
        if self.result_domain != "TELEPHONY":
            raise ValidationError("Only telephony results may update telephony state.")
        if self.campaign_id != projection.campaign_id:
            raise ValidationError("Telephony result campaign binding is invalid.")
        if self.source_environment.upper() != projection.record_environment:
            raise ValidationError("Telephony result environment binding is invalid.")
        if self.application_hash and self.application_hash != application_hash:
            raise ValidationError("Conflicting telephony result application.")
        if self.application_hash == application_hash and self.application_status in {
            "READBACK_VERIFIED",
            "READBACK_MISMATCH",
            "STALE",
        }:
            return self

        now = fields.Datetime.now()
        stale = self.requested_state_version < projection.desired_state_version
        mismatch = (
            observed_state_version != projection.desired_state_version
            or observed_state_hash != projection.desired_state_hash
        )
        drift = False
        previous_drift = projection.last_reconciliation_drift_id
        if stale or mismatch:
            drift = self.env["codestra.integration.reconciliation.drift"].create(
                {
                    "reconciliation_run_id": reconciliation_run.id,
                    "aggregate_model": projection._name,
                    "aggregate_public_id": projection.state_public_id,
                    "source_system": "ODOO",
                    "target_system": mapping.target_system,
                    "target_resource_type": mapping.target_resource_type,
                    "target_public_id": mapping.target_public_id,
                    "drift_type": "VERSION_MISMATCH" if stale else "STATE_MISMATCH",
                    "severity": "ERROR",
                    "expected_state_version": projection.desired_state_version,
                    "observed_state_version": observed_state_version,
                    "expected_state_hash": projection.desired_state_hash,
                    "observed_state_hash": observed_state_hash,
                    "repair_eligibility": "MANUAL_ONLY",
                    "projection_id": projection.id,
                    "mapping_id": mapping.id,
                    "employee_id": projection.employee_id.id,
                    "campaign_id": projection.campaign_id.id,
                    "command_public_id": self.operation_public_id,
                }
            )

        if not stale:
            mapping._apply_readback(
                result=self,
                status=mapping_status,
                observed_state_version=observed_state_version,
                observed_state_hash=observed_state_hash,
            )
            projection.apply_observed_result(
                result=self,
                observed_state=observed_state,
                actual_state_version=observed_state_version,
                observed_state_hash=observed_state_hash,
                adapter_operation_id=self.operation_public_id,
                observed_values=observed_values,
            )
            projection.with_context(
                _codestra_telephony_result_capability=RESULT_APPLICATION_CAPABILITY
            ).write(
                {
                    "last_reconciliation_run_id": reconciliation_run.id,
                    "last_reconciliation_drift_id": drift.id if drift else False,
                }
            )
            if not mismatch and previous_drift:
                previous_drift._resolve_from_verified_readback(
                    self, "Verified readback matches desired telephony state."
                )

        status = (
            "STALE"
            if stale
            else "READBACK_MISMATCH"
            if mismatch
            else "READBACK_VERIFIED"
        )
        self.with_context(
            _codestra_telephony_result_write_capability=
                TELEPHONY_RESULT_WRITE_CAPABILITY
        ).write(
            {
                "applied_state_version": 0
                if stale
                else self.requested_state_version,
                "observed_state_version": observed_state_version,
                "application_status": status,
                "readback_status": status,
                "application_hash": application_hash,
                "readback_hash": observed_state_hash,
                "applied_at": False if stale else now,
                "readback_at": now,
                "mapping_id": mapping.id,
                "projection_id": projection.id,
                "reconciliation_run_id": reconciliation_run.id,
                "reconciliation_drift_id": drift.id if drift else False,
                "safe_result_summary": safe_summary,
                "safe_readback_summary": safe_summary,
            }
        )
        return self
