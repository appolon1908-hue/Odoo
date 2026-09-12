import copy
import uuid

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCodestraKyqraData(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.service_group = cls.env.ref(
            "codestra_kyqra_review_hub.group_kyqra_service"
        )
        cls.reviewer_group = cls.env.ref(
            "codestra_kyqra_review_hub.group_kyqra_reviewer"
        )
        cls.env.user.write(
            {
                "group_ids": [
                    (4, cls.service_group.id),
                    (4, cls.reviewer_group.id),
                ]
            }
        )
        params = cls.env["ir.config_parameter"].sudo()
        params.set_param("codestra.kyqra.tenant_ids", "tenant-1")
        params.set_param(
            "codestra.middleware.tenant.tenant-1.codestra.kyqra.service_user_id",
            str(cls.env.user.id),
        )
        params.set_param(
            "codestra.kyqra.tenant.tenant-1.company_id",
            str(cls.env.company.id),
        )

    def _event(
        self,
        *,
        event_id="kyqra-event-1",
        idempotency_key="kyqra-idem-1",
        tenant_id="tenant-1",
        data=None,
    ):
        result_data = data or {
            "entity_type": "business",
            "name": "Example Logistics",
            "website": "https://example.invalid",
            "confidence": 0.81,
        }
        return {
            "event_id": event_id,
            "event_type": "codestra.crawler.job.completed",
            "event_version": "1.0",
            "occurred_at": "2026-09-12T12:00:00Z",
            "received_at": "2026-09-12T12:00:01Z",
            "source": "kyqra-gateway",
            "tenant_id": tenant_id,
            "customer_id": None,
            "correlation_id": "correlation-1",
            "causation_id": "job-1",
            "idempotency_key": idempotency_key,
            "payload": {
                "job_id": "job-1",
                "status": "completed",
                "error": None,
                "progress": {"processed": 1, "records": 1, "failed": 0},
                "results": [
                    {
                        "record_id": "record-1",
                        "source_url": "https://example.invalid/page",
                        "data": result_data,
                        "provenance": {
                            "source_url": "https://example.invalid/page",
                            "content_digest": "a" * 64,
                            "captured_at": "2026-09-12T12:00:00Z",
                        },
                        "review_required": True,
                        "confidence": 0.81,
                        "capture_method": "http",
                    }
                ],
            },
            "metadata": {
                "origin_service": "kyqra-crawler",
                "contract": "kyqra-crawler-v1",
                "review_policy": "review_pending",
            },
        }

    def test_creates_immutable_review_projection_and_exact_retry_is_duplicate(self):
        first = self.env["codestra.kyqra.batch"].apply_middleware_event(self._event())
        batch = self.env["codestra.kyqra.batch"].browse(first["batch_id"])
        self.assertEqual(first["action"], "created")
        self.assertEqual(first["entity_count"], 1)
        self.assertTrue(first["review_required"])
        self.assertFalse(first["allow_external_contact"])
        self.assertEqual(batch.state, "review_pending")
        self.assertEqual(batch.entity_ids[0].display_name, "Example Logistics")
        self.assertEqual(batch.entity_ids[0].evidence_ids[0].content_digest, "a" * 64)
        duplicate = self.env["codestra.kyqra.batch"].apply_middleware_event(self._event())
        self.assertEqual(duplicate["action"], "duplicate")
        self.assertEqual(duplicate["batch_id"], batch.id)

    def test_same_event_id_with_changed_content_is_rejected(self):
        self.env["codestra.kyqra.batch"].apply_middleware_event(self._event())
        changed = copy.deepcopy(self._event(data={"name": "Changed"}))
        with self.assertRaises(ValidationError):
            self.env["codestra.kyqra.batch"].apply_middleware_event(changed)

    def test_review_actions_do_not_enable_external_contact(self):
        result = self.env["codestra.kyqra.batch"].apply_middleware_event(self._event())
        batch = self.env["codestra.kyqra.batch"].browse(result["batch_id"])
        batch.action_approve()
        self.assertEqual(batch.state, "approved")
        self.assertEqual(batch.entity_ids.review_state, "approved")
        self.assertFalse(batch.allow_external_contact)
        self.assertTrue(batch.review_required)

    def test_direct_mutation_and_deletion_are_blocked(self):
        result = self.env["codestra.kyqra.batch"].apply_middleware_event(self._event())
        batch = self.env["codestra.kyqra.batch"].browse(result["batch_id"])
        entity = batch.entity_ids
        evidence = entity.evidence_ids
        with self.assertRaises(AccessError):
            batch.write({"job_id": "bypass"})
        with self.assertRaises(AccessError):
            entity.write({"data_json": {}})
        with self.assertRaises(AccessError):
            evidence.unlink()
        with self.assertRaises(AccessError):
            batch.unlink()

    def test_wrong_tenant_and_missing_service_binding_are_rejected(self):
        rogue = self._event(
            event_id="kyqra-rogue-1",
            idempotency_key="kyqra-rogue-idem",
            tenant_id="tenant-rogue",
        )
        with self.assertRaises(AccessError):
            self.env["codestra.kyqra.batch"].apply_middleware_event(rogue)
        params = self.env["ir.config_parameter"].sudo()
        key = "codestra.middleware.tenant.tenant-1.codestra.kyqra.service_user_id"
        params.set_param(key, "0")
        try:
            with self.assertRaises(AccessError):
                self.env["codestra.kyqra.batch"].apply_middleware_event(self._event())
        finally:
            params.set_param(key, str(self.env.user.id))

    def test_result_policy_and_secret_keys_fail_closed(self):
        invalid = copy.deepcopy(self._event())
        invalid["payload"]["results"][0]["review_required"] = False
        with self.assertRaises(ValidationError):
            self.env["codestra.kyqra.batch"].apply_middleware_event(invalid)
        invalid = copy.deepcopy(self._event())
        invalid["payload"]["results"][0]["data"]["password"] = "secret"
        with self.assertRaises(ValidationError):
            self.env["codestra.kyqra.batch"].apply_middleware_event(invalid)
        invalid = copy.deepcopy(self._event())
        invalid["payload"]["results"][0]["source_url"] = "http://example.invalid/page"
        with self.assertRaises(ValidationError):
            self.env["codestra.kyqra.batch"].apply_middleware_event(invalid)

    def test_non_reviewer_cannot_approve(self):
        user = self.env["res.users"].create(
            {
                "name": "Kyqra Read User",
                "login": f"kyqra-read-{uuid.uuid4()}@example.invalid",
                "group_ids": [
                    (6, 0, [self.env.ref("base.group_user").id]),
                ],
            }
        )
        result = self.env["codestra.kyqra.batch"].apply_middleware_event(self._event())
        batch = self.env["codestra.kyqra.batch"].browse(result["batch_id"])
        with self.assertRaises(AccessError):
            batch.with_user(user).action_approve()
