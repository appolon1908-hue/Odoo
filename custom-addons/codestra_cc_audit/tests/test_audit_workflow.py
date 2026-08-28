from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestGovernedAuditWorkflow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["cc.business.unit"]._adopt_legacy_records()
        cls.campaign = cls.env["cc.campaign"].with_context(active_test=False).search(
            [], limit=1
        )
        if not cls.campaign:
            raise AssertionError("Synthetic audit campaign was not adopted")
        cls.global_admin = cls._create_user(
            "Audit Global Administrator",
            "cc-audit-global@example.invalid",
            ["codestra_cc_security.group_cc_global_administrator"],
        )
        cls.compliance = cls._create_user(
            "Audit Compliance Approver",
            "cc-audit-compliance@example.invalid",
            ["codestra_cc_security.group_cc_compliance_officer"],
        )
        cls.technical = cls._create_user(
            "Audit Technical Administrator",
            "cc-audit-technical@example.invalid",
            ["codestra_cc_security.group_cc_technical_administrator"],
        )
        cls.other_technical = cls._create_user(
            "Other Technical Administrator",
            "cc-audit-other-technical@example.invalid",
            ["codestra_cc_security.group_cc_technical_administrator"],
        )
        cls.audit_service = cls._create_user(
            "Audit Append Service",
            "cc-audit-service@example.invalid",
            ["codestra_cc_audit.group_cc_audit_service"],
        )

    @classmethod
    def _create_user(cls, name, login, group_xmlids):
        groups = cls.env["res.groups"].browse(
            [cls.env.ref(xmlid).id for xmlid in group_xmlids]
        )
        return cls.env["res.users"].create(
            {"name": name, "login": login, "group_ids": [(6, 0, groups.ids)]}
        )

    def _grant(self, technical, suffix):
        now = fields.Datetime.now()
        grant = self.env["cc.break.glass.grant"].with_user(technical).create(
            {
                "user_id": technical.id,
                "reason": "Synthetic staging incident response",
                "source_ticket": f"INC-AUDIT-{suffix}",
                "starts_at": now - timedelta(minutes=1),
                "ends_at": now + timedelta(hours=1),
            }
        )
        grant.with_user(technical).action_submit()
        grant.with_user(self.compliance).action_activate()
        return grant

    def test_direct_audit_mutation_and_raw_export_are_denied(self):
        with self.assertRaises(AccessError):
            self.env["cc.audit.event"].with_user(self.global_admin).create(
                {
                    "event_uuid": "forged-audit-event",
                    "actor_id": self.global_admin.id,
                    "actor_role": "global_administrator",
                    "company_id": self.env.company.id,
                    "event_type": "cc.forged.v1",
                    "action": "forge",
                    "result": "success",
                    "target_model": "res.users",
                    "idempotency_key": "forged-audit-event",
                    "payload_hash": "a" * 64,
                    "previous_hash": "0" * 64,
                    "record_hash": "b" * 64,
                }
            )
        event = self.env["cc.audit.event"].with_user(self.audit_service)._append_event(
            event_type="cc.synthetic.audit.v1",
            action="synthetic_audit",
            result="success",
            target_model="cc.campaign",
            idempotency_key="audit-synthetic-immutable-001",
            metadata={"scope": "staging"},
        )
        with self.assertRaises(AccessError):
            event.with_user(self.global_admin).write({"result": "failure"})
        with self.assertRaises(AccessError):
            event.with_user(self.global_admin).unlink()
        with self.assertRaises(UserError):
            event.with_user(self.global_admin).export_data(["event_type"])

    def test_append_is_idempotent_rejects_drift_and_verifies_actor_chain(self):
        Audit = self.env["cc.audit.event"].with_user(self.audit_service)
        values = {
            "event_type": "cc.synthetic.integration.v1",
            "action": "integration_readback",
            "result": "success",
            "target_model": "cc.campaign",
            "idempotency_key": "audit-synthetic-idempotent-001",
            "correlation_id": "audit-correlation-001",
            "metadata": {"readback": "matched", "rows": 1},
        }
        event = Audit._append_event(**values)
        replay = Audit._append_event(**values)
        self.assertEqual(event, replay)
        self.assertEqual(len(event.payload_hash), 64)
        self.assertEqual(len(event.record_hash), 64)
        with self.assertRaises(ValidationError):
            Audit._append_event(**{**values, "result": "failure"})
        self.assertTrue(
            self.env["cc.audit.event"].with_user(self.global_admin).verify_chain()
        )

    def test_secret_bearing_metadata_is_rejected_before_append(self):
        with self.assertRaises(ValidationError):
            self.env["cc.audit.event"].with_user(self.audit_service)._append_event(
                event_type="cc.synthetic.secret.v1",
                action="unsafe_log",
                result="blocked",
                target_model="cc.campaign",
                idempotency_key="audit-secret-rejected-001",
                metadata={"api_key": "must-not-be-logged"},
            )

    def test_break_glass_request_approval_use_and_revocation_are_audited(self):
        grant = self._grant(self.technical, "USE-001")
        use_event = grant.with_user(self.technical).action_record_use(
            target_model="cc.campaign",
            target_record_id=self.campaign.id,
            reason="Synthetic emergency inspection",
            idempotency_key="break-glass-use-001",
        )
        self.assertEqual(use_event.event_type, "cc.break_glass.used.v1")
        self.assertFalse(use_event.reason_hash == "")
        grant.with_user(self.technical).action_revoke()
        event_types = self.env["cc.audit.event"].with_user(
            self.global_admin
        ).search([("target_model", "=", "cc.break.glass.grant")]).mapped("event_type")
        self.assertTrue(
            {
                "cc.break_glass.requested.v1",
                "cc.break_glass.submitted.v1",
                "cc.break_glass.activated.v1",
                "cc.break_glass.revoked.v1",
            }.issubset(set(event_types))
        )

    def test_technical_administrator_sees_only_own_minimized_audit(self):
        first = self._grant(self.technical, "SCOPE-A")
        second = self._grant(self.other_technical, "SCOPE-B")
        own_events = self.env["cc.audit.event"].with_user(self.technical).search([])
        self.assertTrue(own_events)
        self.assertEqual(set(own_events.mapped("actor_id").ids), {self.technical.id})
        self.assertNotIn(second.id, own_events.mapped("target_record_id"))
        first.with_user(self.technical).action_revoke()
        second.with_user(self.other_technical).action_revoke()
