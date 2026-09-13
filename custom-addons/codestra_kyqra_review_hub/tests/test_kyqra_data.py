import copy
import uuid

from odoo.exceptions import AccessError, UserError, ValidationError
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
        self.assertEqual(batch.entity_ids[0].name, "Example Logistics")
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

    def test_batch_actions_preserve_existing_entity_decisions(self):
        rejected_result = self.env["codestra.kyqra.batch"].apply_middleware_event(
            self._event()
        )
        rejected_batch = self.env["codestra.kyqra.batch"].browse(
            rejected_result["batch_id"]
        )
        rejected_entity = rejected_batch.entity_ids
        rejected_entity.action_reject()
        with self.assertRaises(UserError):
            rejected_batch.action_approve()
        self.assertEqual(rejected_batch.state, "review_pending")
        self.assertEqual(rejected_entity.review_state, "rejected")

        approved_result = self.env["codestra.kyqra.batch"].apply_middleware_event(
            self._event(
                event_id="kyqra-event-2",
                idempotency_key="kyqra-idem-2",
            )
        )
        approved_batch = self.env["codestra.kyqra.batch"].browse(
            approved_result["batch_id"]
        )
        approved_entity = approved_batch.entity_ids
        approved_entity.action_approve()
        with self.assertRaises(UserError):
            approved_batch.action_reject()
        self.assertEqual(approved_batch.state, "review_pending")
        self.assertEqual(approved_entity.review_state, "approved")

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
        for secret_key in (
            "api_key",
            "authorization",
            "cookie",
            "credential",
            "secret",
            "token",
            "APIKey",
            "clientSecret",
            "apikey",
            "accesstoken",
            "clientsecret",
            "AWS_SECRET_ACCESS_KEY",
            "awssecretaccesskey",
            "serviceSecretKey",
            "tenant-access-key",
            "provider-token",
            "userPassword",
        ):
            with self.subTest(secret_key=secret_key):
                invalid = copy.deepcopy(self._event())
                invalid["payload"]["results"][0]["data"][secret_key] = "secret"
                with self.assertRaises(ValidationError):
                    self.env["codestra.kyqra.batch"].apply_middleware_event(invalid)
        invalid = copy.deepcopy(self._event())
        invalid["payload"]["results"][0]["source_url"] = "http://example.invalid/page"
        with self.assertRaises(ValidationError):
            self.env["codestra.kyqra.batch"].apply_middleware_event(invalid)
        for source_url in (
            "https://example.invalid/page?api_key=secret",
            "https://example.invalid/page?APIKey=secret",
            "https://example.invalid/page?apikey=secret",
            "https://example.invalid/page?accesstoken=secret",
            "https://example.invalid/page?clientsecret=secret",
            "https://example.invalid/page?AWS_SECRET_ACCESS_KEY=secret",
            "https://example.invalid/page?awssecretaccesskey=secret",
            "https://example.invalid/page?serviceSecretKey=secret",
            "https://example.invalid/page?x-api-key=secret",
            "https://example.invalid/page?safe=value;token=secret",
            "https://example.invalid/page?api%5Fkey=secret",
            "https://example.invalid/page#access_token=secret",
        ):
            with self.subTest(source_url=source_url):
                invalid = copy.deepcopy(self._event())
                invalid["payload"]["results"][0]["source_url"] = source_url
                with self.assertRaises(ValidationError):
                    self.env["codestra.kyqra.batch"].apply_middleware_event(invalid)
        invalid = copy.deepcopy(self._event())
        invalid["payload"]["results"][0]["provenance"]["source_url"] = (
            "https://example.invalid/page?token=secret"
        )
        with self.assertRaises(ValidationError):
            self.env["codestra.kyqra.batch"].apply_middleware_event(invalid)

    def test_source_url_authority_and_encoding_are_strict(self):
        for source_url in (
            " https://example.invalid/path",
            "https://example.invalid/path ",
            "\nhttps://example.invalid/path\r",
            "https://example.invalid:bad/path",
            "https://exa mple.invalid/path",
            "https://example.invalid:70000/path",
            "https://example.invalid:/path",
            "https://bad_label.example/path",
            "https://999.999.999.999/path",
            "https://example.invalid/%ZZ",
            "https://example.invalid/path%0d%0anext",
            "https://example.invalid/%C3%28",
            "https://example.invalid\\@attacker.invalid/path",
            "https://[not-ipv6]/path",
        ):
            with self.subTest(source_url=source_url):
                invalid = copy.deepcopy(self._event())
                result = invalid["payload"]["results"][0]
                result["source_url"] = source_url
                result["provenance"]["source_url"] = source_url
                with self.assertRaises(ValidationError):
                    self.env["codestra.kyqra.batch"].apply_middleware_event(invalid)

        for index, source_url in enumerate(
            (
                "https://example.invalid:8443/path?page=2&sort=name",
                "https://xn--bcher-kva.example/path",
                "https://[2001:db8::1]:443/path",
            ),
            start=1,
        ):
            with self.subTest(source_url=source_url):
                event = self._event(
                    event_id=f"kyqra-url-event-{index}",
                    idempotency_key=f"kyqra-url-idem-{index}",
                )
                item = event["payload"]["results"][0]
                item["source_url"] = source_url
                item["provenance"]["source_url"] = source_url
                created = self.env["codestra.kyqra.batch"].apply_middleware_event(
                    event
                )
                entity = self.env["codestra.kyqra.batch"].browse(
                    created["batch_id"]
                ).entity_ids
                self.assertEqual(entity.source_url, source_url)
                self.assertEqual(entity.evidence_ids.source_url, source_url)

    def test_retained_identifier_whitespace_fails_closed(self):
        invalid = copy.deepcopy(self._event())
        invalid["event_id"] = " kyqra-event-1 "
        with self.assertRaises(ValidationError):
            self.env["codestra.kyqra.batch"].apply_middleware_event(invalid)

    def test_invalid_rfc3339_timestamps_fail_closed(self):
        for field_name, invalid_value in (
            ("occurred_at", "unknown"),
            ("received_at", "2026-09-12T12:00:01"),
            ("occurred_at", "2026-02-30T12:00:00Z"),
            ("occurred_at", " 2026-09-12T12:00:00Z"),
            ("received_at", "\n2026-09-12T12:00:01Z\r"),
        ):
            with self.subTest(field_name=field_name, invalid_value=invalid_value):
                invalid = copy.deepcopy(self._event())
                invalid[field_name] = invalid_value
                with self.assertRaises(ValidationError):
                    self.env["codestra.kyqra.batch"].apply_middleware_event(invalid)
        invalid = copy.deepcopy(self._event())
        invalid["payload"]["results"][0]["provenance"]["captured_at"] = (
            "2026-09-12T12:00:00"
        )
        with self.assertRaises(ValidationError):
            self.env["codestra.kyqra.batch"].apply_middleware_event(invalid)

    def test_rfc3339_timestamps_are_normalized_to_utc(self):
        event = self._event()
        event["occurred_at"] = "2026-09-12T14:00:00+02:00"
        event["received_at"] = "2026-09-12T07:30:00.123-04:30"
        event["payload"]["results"][0]["provenance"]["captured_at"] = (
            "2026-09-12T13:00:00+01:00"
        )
        result = self.env["codestra.kyqra.batch"].apply_middleware_event(event)
        batch = self.env["codestra.kyqra.batch"].browse(result["batch_id"])
        self.assertEqual(batch.occurred_at, "2026-09-12T12:00:00Z")
        self.assertEqual(batch.received_at, "2026-09-12T12:00:00.123000Z")
        self.assertEqual(
            batch.entity_ids.evidence_ids.captured_at,
            "2026-09-12T12:00:00Z",
        )

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
