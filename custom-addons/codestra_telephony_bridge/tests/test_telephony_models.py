import uuid

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged
from psycopg2 import IntegrityError

from ..hooks import post_init_hook
from ..models.telephony import canonical_hash


@tagged("post_install", "-at_install")
class TestTelephonyModels(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env["call.center.business.unit"].create(
            {"name": "Synthetic Unit", "code": f"T{uuid.uuid4().hex[:5]}"}
        )
        cls.campaign = cls.env["call.center.campaign"].create(
            {
                "name": "Synthetic Campaign",
                "code": f"C{uuid.uuid4().hex[:5]}",
                "business_unit_id": cls.unit.id,
            }
        )
        cls.employee = cls.env["hr.employee"].create({"name": "Synthetic Agent"})

    def _desired_values(self):
        return {
            "record_environment": "TEST",
            "employee_id": self.employee.id,
            "business_unit_id": self.unit.id,
            "campaign_id": self.campaign.id,
            "desired_enabled": False,
            "desired_campaign_membership": False,
            "desired_transfer_permission": False,
            "desired_callback_permission": False,
            "desired_external_call_permission": False,
        }

    def test_desired_state_hash_and_version_are_model_controlled(self):
        state = self.env["codestra.telephony.desired.state"].create(
            self._desired_values()
        )
        self.assertEqual(state.desired_state_version, 1)
        self.assertEqual(
            state.desired_state_hash,
            canonical_hash(
                {
                    "desired_enabled": False,
                    "desired_campaign_membership": False,
                    "desired_transfer_permission": False,
                    "desired_callback_permission": False,
                    "desired_external_call_permission": False,
                    "desired_endpoint_context_key": None,
                    "desired_phone_active": False,
                    "desired_user_active": False,
                    "phone_public_id": None,
                    "endpoint_public_id": None,
                    "extension": None,
                    "allocation_reservation_public_id": None,
                }
            ),
        )
        state.write({"desired_callback_permission": True})
        self.assertEqual(state.desired_state_version, 2)
        with self.assertRaises(AccessError):
            state.write({"actual_state_version": 2})

    def test_employee_campaign_state_is_unique(self):
        self.env["codestra.telephony.desired.state"].create(self._desired_values())
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env["codestra.telephony.desired.state"].create(
                self._desired_values()
            )

    def test_cross_business_unit_campaign_is_rejected(self):
        other = self.env["call.center.business.unit"].create(
            {"name": "Other Unit", "code": f"O{uuid.uuid4().hex[:5]}"}
        )
        values = self._desired_values()
        values["business_unit_id"] = other.id
        with self.assertRaises(ValidationError):
            self.env["codestra.telephony.desired.state"].create(values)

    def test_reconciliation_drift_binding_is_unique(self):
        run = self.env["codestra.integration.reconciliation.run"].create(
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
            }
        )
        values = {
            "reconciliation_run_id": run.id,
            "aggregate_model": "hr.employee",
            "aggregate_public_id": f"AGT-{uuid.uuid4()}",
            "source_system": "ODOO",
            "target_system": "ASTERISK",
            "target_resource_type": "ENDPOINT",
            "target_public_id": f"END-{uuid.uuid4()}",
            "drift_type": "MISSING_TARGET",
            "severity": "ERROR",
            "repair_eligibility": "MANUAL_ONLY",
        }
        self.env["codestra.integration.reconciliation.drift"].create(values)
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env["codestra.integration.reconciliation.drift"].create(values)

    def test_duplicate_model_definitions_are_absent(self):
        registry = self.env.registry
        for model_name in (
            "codestra.runtime.integration.outbox",
            "codestra.integration.result.inbox",
            "codestra.integration.trace",
            "call.center.callback.task",
            "codestra.extension.assignment",
            "codestra.identity.link",
        ):
            self.assertIn(model_name, registry)
        self.assertNotIn("codestra.integration.reaction", registry)
        self.assertNotIn("codestra.telephony.callback", registry)

    def test_reconciliation_evidence_is_not_deletable(self):
        run = self.env["codestra.integration.reconciliation.run"].create(
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
            }
        )
        with self.assertRaises(AccessError):
            run.unlink()

    def test_callback_backfill_is_stable_and_idempotent(self):
        lead = self.env["crm.lead"].create(
            {
                "name": "Synthetic Callback Backfill",
                "business_unit_id": self.unit.id,
                "call_center_campaign_id": self.campaign.id,
            }
        )
        callback = self.env["call.center.callback.task"].create(
            {
                "business_unit_id": self.unit.id,
                "lead_id": lead.id,
                "campaign_id": self.campaign.id,
                "agent_id": self.env.user.id,
                "supervisor_id": self.env.user.id,
                "due_at": fields.Datetime.now(),
                "correlation_id": f"backfill-{uuid.uuid4()}",
            }
        )
        callback.write({"callback_public_id": False, "idempotency_key": False})

        post_init_hook(self.env)
        first_binding = (callback.callback_public_id, callback.idempotency_key)
        self.assertTrue(all(first_binding))

        post_init_hook(self.env)
        self.assertEqual(
            (callback.callback_public_id, callback.idempotency_key),
            first_binding,
        )
