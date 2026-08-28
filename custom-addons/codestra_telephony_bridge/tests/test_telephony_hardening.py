import uuid

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged
from psycopg2 import IntegrityError

from ..models.telephony_hardening import MAPPING_APPLICATION_CAPABILITY


@tagged("post_install", "-at_install")
class TestTelephonyHardening(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env.ref("call_center_core.business_unit_digital")
        cls.campaign = cls.env["call.center.campaign"].create(
            {
                "name": "Hardening Campaign",
                "code": f"HC{uuid.uuid4().hex[:6]}",
                "business_unit_id": cls.unit.id,
                "direction": "outbound",
                "purpose_code": "TEST",
                "design_automation_enabled": True,
            }
        )
        cls.employee = cls.env["hr.employee"].create(
            {
                "name": "Hardening Agent",
                "codestra_employee_number": f"AGT-{uuid.uuid4().hex[:10]}",
            }
        )
        cls.lead = cls.env["crm.lead"].create(
            {
                "name": "Hardening Synthetic Lead",
                "business_unit_id": cls.unit.id,
                "call_center_campaign_id": cls.campaign.id,
            }
        )
        cls.outbox = cls.env["codestra.runtime.integration.outbox"].sudo().search(
            [("campaign_id", "=", cls.campaign.id)], limit=1
        )

    def _projection(self):
        return self.env["codestra.telephony.desired.state"].create(
            {
                "record_environment": "TEST",
                "employee_id": self.employee.id,
                "business_unit_id": self.unit.id,
                "campaign_id": self.campaign.id,
                "desired_enabled": False,
                "desired_campaign_membership": False,
                "desired_callback_permission": False,
                "desired_transfer_permission": False,
                "desired_external_call_permission": False,
                "desired_endpoint_context_key": "codestra_test_restricted",
                "desired_phone_active": False,
                "desired_user_active": False,
            }
        )

    def _mapping_values(self, target_public_id=None):
        return {
            "environment": "TEST",
            "employee_id": self.employee.id,
            "agent_public_id": self.employee.codestra_employee_number,
            "business_unit_id": self.unit.id,
            "business_unit_public_id": self.unit.code,
            "campaign_id": self.campaign.id,
            "campaign_public_id": self.campaign.code,
            "target_system": "ASTERISK_ENDPOINT",
            "target_resource_type": "ENDPOINT",
            "target_public_id": target_public_id or f"END-{uuid.uuid4()}",
            "desired_state_version": 1,
            "mapping_status": "PROVISIONING",
        }

    def _run(self, key=None):
        return self.env["codestra.integration.reconciliation.run"].get_or_create_scan(
            {
                "environment": "TEST",
                "scope_type": "CAMPAIGN",
                "business_unit_id": self.unit.id,
                "campaign_id": self.campaign.id,
                "target_system": "ASTERISK",
                "trigger_type": "ON_DEMAND",
                "triggered_by": "synthetic-test",
                "configuration_version": "1",
                "policy_hash": "a" * 64,
                "scan_idempotency_key": key or str(uuid.uuid4()),
            }
        )

    def _result(self, projection, requested_version=None, source_environment="test"):
        result_id = str(uuid.uuid4())
        return (
            self.env["codestra.integration.result.inbox"]
            .sudo()
            ._create_from_callback(
                {
                    "name": result_id,
                    "result_public_id": result_id,
                    "schema_version": "1.0",
                    "delivery_id": str(uuid.uuid4()),
                    "event_id": self.outbox.event_uuid,
                    "registration_id": str(uuid.uuid4()),
                    "acknowledgement_id": str(uuid.uuid4()),
                    "correlation_id": self.outbox.correlation_id,
                    "workflow_id": "logical-telephony-readback",
                    "workflow_version": "1.0.0",
                    "execution_id": str(uuid.uuid4()),
                    "execution_status": "SUCCEEDED",
                    "result_classification": "TELEPHONY_READBACK",
                    "result_hash": "b" * 64,
                    "organization_public_id": "ORG-TEST",
                    "business_unit_id": self.unit.id,
                    "campaign_id": self.campaign.id,
                    "source_system": "codestra-middleware",
                    "source_environment": source_environment,
                    "policy_hash": "c" * 64,
                    "originating_outbox_id": self.outbox.id,
                    "originating_model": self.campaign._name,
                    "originating_res_id": self.campaign.id,
                    "received_at": "2026-07-29 09:00:00",
                    "acknowledged_at": "2026-07-29 09:00:00",
                    "processing_status": "RECEIVED",
                    "reconciliation_status": "RECONCILED",
                    "payload_json_redacted": {"summary": "synthetic"},
                    "request_hash": "d" * 64,
                    "created_by_service": "codestra-middleware",
                    "result_domain": "TELEPHONY",
                    "operation_public_id": str(uuid.uuid4()),
                    "target_system": "ASTERISK_ENDPOINT",
                    "target_resource_type": "ENDPOINT",
                    "target_public_id": f"END-{uuid.uuid4()}",
                    "command_type": "agent.telephony.readback",
                    "operation_type": "READBACK",
                    "requested_state_version": requested_version
                    or projection.desired_state_version,
                }
            )
        )

    def _transfer_values(self, key=None):
        return {
            "record_environment": "TEST",
            "business_unit_id": self.unit.id,
            "lead_id": self.lead.id,
            "campaign_id": self.campaign.id,
            "call_public_id": f"CALL-{uuid.uuid4()}",
            "source_agent_id": self.env.user.id,
            "source_agent_public_id": self.employee.codestra_employee_number,
            "transfer_type": "ATTENDED",
            "source_extension": "synthetic-extension",
            "target_classification": "QUEUE",
            "target_reference": "synthetic-internal-queue",
            "correlation_id": str(uuid.uuid4()),
            "idempotency_key": key or str(uuid.uuid4()),
        }

    def test_target_mapping_active_resource_is_unique(self):
        values = self._mapping_values()
        self.env["codestra.telephony.target.mapping"].create(values)
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env["codestra.telephony.target.mapping"].create(values)

    def test_result_applies_matching_readback_idempotently(self):
        projection = self._projection()
        mapping = self.env["codestra.telephony.target.mapping"].create(
            self._mapping_values()
        )
        run = self._run()
        result = self._result(projection)
        kwargs = {
            "projection": projection,
            "mapping": mapping,
            "reconciliation_run": run,
            "observed_state": "DISABLED",
            "observed_state_version": projection.desired_state_version,
            "observed_state_hash": projection.desired_state_hash,
            "mapping_status": "ACTIVE",
            "application_hash": "e" * 64,
            "safe_summary": "Synthetic readback verified.",
            "observed_values": {
                "observed_asterisk_endpoint_exists": True,
                "observed_asterisk_endpoint_enabled": False,
                "observed_registration_status": "UNREGISTERED",
            },
        }
        self.assertEqual(result._apply_telephony_readback(**kwargs), result)
        self.assertEqual(result._apply_telephony_readback(**kwargs), result)
        self.assertEqual(result.application_status, "READBACK_VERIFIED")
        self.assertEqual(projection.reconciliation_status, "IN_SYNC")
        self.assertEqual(mapping.mapping_status, "ACTIVE")

        with self.assertRaises(ValidationError):
            result._apply_telephony_readback(
                **dict(kwargs, application_hash="f" * 64)
            )

    def test_stale_result_does_not_regress_desired_state(self):
        projection = self._projection()
        stale_version = projection.desired_state_version
        projection.write({"desired_callback_permission": True})
        desired_version = projection.desired_state_version
        mapping = self.env["codestra.telephony.target.mapping"].create(
            self._mapping_values()
        )
        result = self._result(projection, requested_version=stale_version)
        result._apply_telephony_readback(
            projection=projection,
            mapping=mapping,
            reconciliation_run=self._run(),
            observed_state="DISABLED",
            observed_state_version=stale_version,
            observed_state_hash="f" * 64,
            mapping_status="ACTIVE",
            application_hash="1" * 64,
            safe_summary="Synthetic stale result.",
        )
        self.assertEqual(result.application_status, "STALE")
        self.assertEqual(projection.desired_state_version, desired_version)
        self.assertEqual(projection.actual_state_version, 0)
        self.assertEqual(result.reconciliation_drift_id.drift_type, "VERSION_MISMATCH")

    def test_mismatch_drift_closes_after_verified_readback(self):
        projection = self._projection()
        mapping = self.env["codestra.telephony.target.mapping"].create(
            self._mapping_values()
        )
        run = self._run()
        mismatch = self._result(projection)
        mismatch._apply_telephony_readback(
            projection=projection,
            mapping=mapping,
            reconciliation_run=run,
            observed_state="DISABLED",
            observed_state_version=projection.desired_state_version,
            observed_state_hash="0" * 64,
            mapping_status="ACTIVE",
            application_hash="2" * 64,
            safe_summary="Synthetic mismatch.",
        )
        drift = mismatch.reconciliation_drift_id
        self.assertEqual(drift.drift_type, "STATE_MISMATCH")
        self.assertEqual(projection.reconciliation_status, "DRIFTED")

        verified = self._result(projection)
        verified._apply_telephony_readback(
            projection=projection,
            mapping=mapping,
            reconciliation_run=self._run(),
            observed_state="DISABLED",
            observed_state_version=projection.desired_state_version,
            observed_state_hash=projection.desired_state_hash,
            mapping_status="ACTIVE",
            application_hash="3" * 64,
            safe_summary="Synthetic corrected readback.",
        )
        self.assertEqual(drift.repair_status, "COMPLETED")
        self.assertTrue(drift.resolved_at)
        self.assertEqual(projection.reconciliation_status, "IN_SYNC")

    def test_wrong_environment_result_is_rejected(self):
        projection = self._projection()
        mapping = self.env["codestra.telephony.target.mapping"].create(
            self._mapping_values()
        )
        result = self._result(projection, source_environment="staging")
        with self.assertRaises(ValidationError):
            result._apply_telephony_readback(
                projection=projection,
                mapping=mapping,
                reconciliation_run=self._run(),
                observed_state="DISABLED",
                observed_state_version=projection.desired_state_version,
                observed_state_hash=projection.desired_state_hash,
                mapping_status="ACTIVE",
                application_hash="4" * 64,
                safe_summary="Wrong environment fixture.",
            )

    def test_reconciliation_scan_is_idempotent(self):
        key = str(uuid.uuid4())
        self.assertEqual(self._run(key), self._run(key))

    def test_transfer_history_and_duplicate_binding(self):
        values = self._transfer_values()
        transfer = self.env["codestra.telephony.transfer.request"].create(values)
        duplicate = self.env["codestra.telephony.transfer.request"].create(values)
        self.assertEqual(transfer, duplicate)
        transfer.write({"state": "VALIDATING"})
        transfer.write({"state": "CONNECTING"})
        transfer.write({"state": "CONNECTED"})
        transfer.write({"state": "COMPLETED"})
        self.assertEqual(
            transfer.transition_ids.mapped("to_state"),
            ["REQUESTED", "VALIDATING", "CONNECTING", "CONNECTED", "COMPLETED"],
        )
        conflicting = dict(values, target_reference="other-internal-queue")
        with self.assertRaises(ValidationError):
            self.env["codestra.telephony.transfer.request"].create(conflicting)

    def test_mapping_revocation_cannot_reactivate_and_allocation_is_verified(self):
        mapping = self.env["codestra.telephony.target.mapping"].create(
            self._mapping_values()
        )
        controlled = mapping.with_context(
            _codestra_mapping_application_capability=MAPPING_APPLICATION_CAPABILITY
        )
        controlled.write({"mapping_status": "ACTIVE"})
        controlled.write({"mapping_status": "REVOKED"})
        with self.assertRaises(ValidationError):
            controlled.write({"mapping_status": "ACTIVE"})

        values = self._mapping_values()
        values.update(
            {
                "extension": "synthetic-unallocated-extension",
                "allocation_reservation_public_id": str(uuid.uuid4()),
            }
        )
        with self.assertRaises(ValidationError):
            self.env["codestra.telephony.target.mapping"].create(values)

    def test_transfer_rejection_and_callback_fallback_paths(self):
        rejected = self.env["codestra.telephony.transfer.request"].create(
            self._transfer_values()
        )
        rejected.write({"state": "VALIDATING"})
        rejected.write({"state": "REJECTED"})
        self.assertEqual(rejected.state, "REJECTED")

        fallback = self.env["codestra.telephony.transfer.request"].create(
            self._transfer_values()
        )
        fallback.write({"state": "VALIDATING"})
        fallback.write({"state": "WAITING_FOR_DESTINATION"})
        fallback.write({"state": "FAILED"})
        fallback.write({"state": "CALLBACK_REQUIRED"})
        self.assertEqual(fallback.state, "CALLBACK_REQUIRED")
