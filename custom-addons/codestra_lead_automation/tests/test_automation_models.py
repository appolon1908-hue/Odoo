from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase


class LeadAutomationModelTest(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.campaign = cls.env["call.center.campaign"].with_context(active_test=False).search([], limit=1)
        assert cls.campaign, "synthetic campaign fixture is required"
        cls.unit = cls.campaign.business_unit_id
        cls.lead = cls.env["crm.lead"].create(
            {
                "name": "Synthetic lead automation test",
                "business_unit_id": cls.unit.id,
                "call_center_campaign_id": cls.campaign.id,
                "codestra_lead_uid": "LEAD-synthetic1234",
            }
        )
        model = cls.env["codestra.lead.automation.execution"]
        cls.key = model.stable_idempotency_key(
            "test", cls.unit.code, cls.campaign.code, cls.lead.codestra_lead_uid,
            "UPDATE_ALLOWLISTED_FIELDS", "internal", 1, "policy-1",
        )
        cls.values = {
            "automation_event_id": "LAE-synthetic1234",
            "environment": "test",
            "business_unit_id": cls.unit.id,
            "campaign_id": cls.campaign.id,
            "lead_id": cls.lead.id,
            "lead_public_id": cls.lead.codestra_lead_uid,
            "action": "UPDATE_ALLOWLISTED_FIELDS",
            "channel": "internal",
            "desired_version": 1,
            "policy_version": "policy-1",
            "idempotency_key": cls.key,
            "request_fingerprint": "b" * 64,
        }

    def test_model_registry_and_stable_idempotency(self):
        required = {
            "codestra.lead.automation.policy", "codestra.lead.automation.config",
            "codestra.lead.automation.execution", "codestra.lead.consent.snapshot",
            "codestra.lead.channel.eligibility", "codestra.lead.automation.nonce",
            "codestra.lead.callback.request", "codestra.runtime.integration.outbox",
            "codestra.integration.result.inbox", "codestra.integration.reconciliation.run",
        }
        self.assertFalse(required - set(self.env.registry.models))
        again = self.env["codestra.lead.automation.execution"].stable_idempotency_key(
            "test", self.unit.code, self.campaign.code, self.lead.codestra_lead_uid,
            "UPDATE_ALLOWLISTED_FIELDS", "internal", 1, "policy-1",
        )
        self.assertEqual(self.key, again)
        self.assertEqual(len(self.key), 64)

    def test_idempotent_reuse_and_conflict(self):
        model = self.env["codestra.lead.automation.execution"]
        first = model.get_or_create_idempotent(dict(self.values))
        self.assertEqual(first, model.get_or_create_idempotent(dict(self.values)))
        conflict = dict(self.values, request_fingerprint="c" * 64)
        with self.assertRaises(ValidationError):
            model.get_or_create_idempotent(conflict)

    def test_fail_closed_state_machine_and_terminal_regression(self):
        execution = self.env["codestra.lead.automation.execution"].create(self.values)
        with self.assertRaises(AccessError):
            execution.transition("VALIDATING", "VALID")
        execution = execution.with_context(codestra_lead_automation_system=True)
        execution.transition("VALIDATING", "VALID")
        with self.assertRaises(ValidationError):
            execution.transition("COMPLETED", "INVALID_SKIP")
        execution.transition("POLICY_EVALUATING", "POLICY_CHECK")
        execution.transition("DNC_BLOCKED", "DNC_OVERRIDE")
        with self.assertRaises(ValidationError):
            execution.transition("OUTBOX_PENDING", "REGRESSION")

    def test_missing_consent_denies_and_dnc_overrides(self):
        snapshot = self.env["codestra.lead.consent.snapshot"].with_context(
            codestra_lead_automation_system=True
        ).create({
            "snapshot_public_id": "CSN-synthetic1234",
            "business_unit_id": self.unit.id,
            "lead_id": self.lead.id,
            "campaign_id": self.campaign.id,
            "channel": "phone",
            "purpose": "SALES",
            "consent_status": "granted",
            "consent_source": "odoo",
            "consent_timestamp": "2026-07-31 12:00:00",
            "dnc": True,
            "dnc_source": "odoo",
            "dnc_timestamp": "2026-07-31 12:00:00",
        })
        self.assertFalse(snapshot.is_eligible())
        with self.assertRaises(AccessError):
            snapshot.write({"dnc": False})

    def test_persistent_nonce_replay_and_security_inventory(self):
        nonce = self.env["codestra.lead.automation.nonce"]
        nonce.consume("test", "codestra-middleware", "synthetic-nonce")
        with self.assertRaises(ValidationError):
            nonce.consume("test", "codestra-middleware", "synthetic-nonce")
        for xmlid in (
            "codestra_lead_automation.group_lead_automation_agent",
            "codestra_lead_automation.group_lead_automation_team_leader",
            "codestra_lead_automation.group_lead_automation_supervisor",
            "codestra_lead_automation.group_lead_automation_campaign_manager",
            "codestra_lead_automation.group_lead_automation_bu_director",
            "codestra_lead_automation.group_lead_automation_integration_admin",
            "codestra_lead_automation.group_lead_automation_admin",
        ):
            self.assertTrue(self.env.ref(xmlid).exists())
