import uuid

from odoo import SUPERUSER_ID, api
from odoo.exceptions import AccessError, ValidationError
from odoo.modules.registry import Registry
from odoo.tests.common import (
    BaseCase,
    TransactionCase,
    get_db_name,
    new_test_user,
    tagged,
)


class TestAudit(TransactionCase):
    def _actor(self, suffix):
        return new_test_user(
            self.env,
            login=f"audit-actor-{suffix}",
            groups="base.group_user",
            context={"no_reset_password": True},
        )

    def test_append_only_chain_and_tamper_detection(self):
        event = self.env["codestra.integration.event"].register_event("x", "odoo", "middleware", {})
        event.validate_event()
        audit = self.env["codestra.integration.audit"].search([("event_id", "=", event.id)])
        self.assertTrue(audit.verify_chain())
        self.assertNotIn("secret-value", audit.metadata_redacted or "")
        with self.assertRaises(AccessError):
            audit.write({"action": "tampered"})
        with self.assertRaises(AccessError):
            audit.unlink()
        with self.assertRaises(AccessError):
            self.env["codestra.integration.audit"].sudo().create({})
        self.env.cr.execute("UPDATE codestra_integration_audit SET record_hash='tampered' WHERE id=%s", [audit.id])
        self.env.invalidate_all()
        with self.assertRaises(ValidationError):
            audit.verify_chain()

    def test_eventless_append_preserves_actor_and_subject(self):
        actor = self._actor("eventless")
        audit = self.env["codestra.integration.audit"].with_user(actor)._append(
            False,
            "call.workspace.viewed",
            "success",
            {
                "model_name": "codestra.vicidial.call",
                "record_res_id": 42,
                "after": {"sequence": 3},
            },
            actor_role="agent",
            correlation_id="corr-eventless-audit",
            subject_model="codestra.vicidial.call",
            subject_id=42,
        )

        self.assertFalse(audit.event_id)
        self.assertEqual(audit.actor_user_id, actor)
        self.assertEqual(audit.actor_id, actor)
        self.assertEqual(audit.actor_role, "agent")
        self.assertEqual(audit.correlation_id, "corr-eventless-audit")
        self.assertEqual(audit.model_name, "codestra.vicidial.call")
        self.assertEqual(audit.record_res_id, 42)
        self.assertTrue(audit.payload_hash)
        self.assertTrue(audit.verify_chain())

    def test_exact_event_anchor_never_rebinds_by_correlation(self):
        actor = self._actor("exact-event")
        correlation_id = "corr-shared-by-two-events"
        first = self.env["codestra.integration.event"].register_event(
            "call.command.answer",
            "odoo",
            "middleware",
            {"command_id": 1},
            correlation_id=correlation_id,
            event_uuid=str(uuid.uuid4()),
            idempotency_key="audit-event-anchor-first",
        )
        second = self.env["codestra.integration.event"].register_event(
            "call.command.hold",
            "odoo",
            "middleware",
            {"command_id": 2},
            correlation_id=correlation_id,
            event_uuid=str(uuid.uuid4()),
            idempotency_key="audit-event-anchor-second",
        )

        audit = self.env["codestra.integration.audit"].with_user(actor)._append(
            first,
            "call.answer",
            "success",
            {
                "model_name": "codestra.vicidial.call",
                "record_res_id": 43,
                "after": {"command_id": 1},
            },
            actor_role="agent",
            correlation_id=correlation_id,
            subject_model="codestra.vicidial.call",
            subject_id=43,
        )

        self.assertEqual(audit.event_id, first)
        self.assertNotEqual(audit.event_id, second)
        self.assertEqual(audit.actor_user_id, actor)
        self.assertEqual(audit.actor_role, "agent")
        self.assertTrue(audit.verify_chain())

    def test_projection_tamper_is_detected_without_changing_legacy_hash_shape(self):
        audit = self.env["codestra.integration.audit"]._append(
            False,
            "call.detail.viewed",
            "success",
            {
                "model_name": "codestra.vicidial.call",
                "record_res_id": 44,
                "after": {"role": "qa"},
            },
            actor_role="qa",
            correlation_id="corr-projection-tamper",
            subject_model="codestra.vicidial.call",
            subject_id=44,
        )
        self.assertTrue(audit.verify_chain())

        self.env.cr.execute(
            "UPDATE codestra_integration_audit SET model_name=%s WHERE id=%s",
            ["tampered.model", audit.id],
        )
        self.env.invalidate_all()
        with self.assertRaises(ValidationError):
            audit.verify_chain()

    def test_invalid_actor_role_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.env["codestra.integration.audit"]._append(
                False,
                "call.workspace.viewed",
                "success",
                {
                    "model_name": "codestra.vicidial.call",
                    "record_res_id": 45,
                    "after": {},
                },
                actor_role="root",
                correlation_id="corr-invalid-role",
                subject_model="codestra.vicidial.call",
                subject_id=45,
            )


@tagged("-at_install", "post_install")
class TestAuditConcurrency(BaseCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.registry = Registry(get_db_name())
        token = uuid.uuid4().hex
        cls.correlations = [
            f"corr-parallel-{token}-one",
            f"corr-parallel-{token}-two",
        ]
        cls.addClassCleanup(cls._remove_test_audits)

    @classmethod
    def _remove_test_audits(cls):
        with cls.registry.cursor() as cr:
            cr.execute(
                """
                DELETE FROM codestra_integration_audit
                 WHERE correlation_id IN %s
                """,
                [tuple(cls.correlations)],
            )

    def test_two_transactions_cannot_fork_the_hash_chain(self):
        def append(env, correlation_id):
            return env["codestra.integration.audit"]._append(
                False,
                "audit.concurrent.append",
                "success",
                {
                    "model_name": "res.users",
                    "record_res_id": SUPERUSER_ID,
                    "after": {"correlation_id": correlation_id},
                },
                actor_role="system",
                correlation_id=correlation_id,
                subject_model="res.users",
                subject_id=SUPERUSER_ID,
            )

        with self.registry.cursor() as first_cr:
            first_env = api.Environment(first_cr, SUPERUSER_ID, {})
            FirstAudit = first_env["codestra.integration.audit"].sudo()
            tail = (
                FirstAudit.search([], order="id desc", limit=1).record_hash
                or ""
            )
            FirstAudit._lock_chain()

            with self.registry.cursor() as second_cr:
                second_env = api.Environment(second_cr, SUPERUSER_ID, {})
                SecondAudit = second_env["codestra.integration.audit"].sudo()
                with self.assertRaises(Exception) as blocked:
                    second_cr.execute(
                        """
                        SELECT id
                          FROM codestra_integration_audit_chain_lock
                         WHERE name = %s
                         FOR UPDATE NOWAIT
                        """,
                        ["global"],
                    )
                self.assertEqual(
                    getattr(blocked.exception, "pgcode", None),
                    "55P03",
                )
                second_cr.rollback()

                first = append(first_env, self.correlations[0])
                first_hash = first.record_hash
                first_cr.commit()

                second = append(second_env, self.correlations[1])
                self.assertEqual(second.previous_hash, first_hash)
                second_cr.commit()

        with self.registry.cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            Audit = env["codestra.integration.audit"].sudo()
            records = Audit.search(
                [("correlation_id", "in", self.correlations)],
                order="id asc",
            )
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0].previous_hash, tail)
            self.assertEqual(
                records[1].previous_hash,
                records[0].record_hash,
            )
            self.assertTrue(Audit.verify_chain())
