import copy
import uuid

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


TENANT_ID = "11111111-1111-4111-8111-111111111111"
BUSINESS_ID = "22222222-2222-4222-8222-222222222222"
EVENT_ID = "33333333-3333-4333-8333-333333333333"
CORRELATION_ID = "44444444-4444-4444-8444-444444444444"


@tagged("post_install", "-at_install")
class TestCodestraScrapperProjection(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        service_group = cls.env.ref(
            "codestra_scrapper_projection.group_scrapper_projection_service"
        )
        cls.env.user.write({"group_ids": [(4, service_group.id)]})
        params = cls.env["ir.config_parameter"].sudo()
        params.set_param("codestra.scrapper.tenant_ids", TENANT_ID)
        params.set_param(
            (
                f"codestra.middleware.tenant.{TENANT_ID}."
                "codestra.scrapper.service_user_id"
            ),
            str(cls.env.user.id),
        )

    def _payload(self, **updates):
        payload = {
            "tenant_id": TENANT_ID,
            "business_id": BUSINESS_ID,
            "event_id": EVENT_ID,
            "correlation_id": CORRELATION_ID,
            "version": 1,
            "company_name": "Example Logistics",
            "website": "https://example.invalid",
            "email": "ops@example.invalid",
            "phone": "+18095550100",
            "country_code": "DO",
            "source_url": "https://source.example.invalid/business/1",
            "source_captured_at": "2026-09-03 12:00:00",
            "adapter_version": "scrapper-adapter/1",
            "mapping_version": "1.0",
            "evidence_summary": {"source_count": 2},
            "confidence": 0.9,
            "projection_status": "projected",
        }
        payload.update(updates)
        return payload

    def _apply(self, payload):
        return self.env[
            "codestra.scrapper.business"
        ].apply_middleware_projection(payload)

    def test_authorized_create_and_exact_replay_are_content_bound(self):
        first = self._apply(self._payload())
        second = self._apply(self._payload())
        projection = self.env["codestra.scrapper.business"].sudo().browse(
            first["projection_id"]
        )
        self.assertEqual(first["result"], "created")
        self.assertFalse(first["duplicate"])
        self.assertEqual(second["result"], "created")
        self.assertTrue(second["duplicate"])
        self.assertEqual(second["projection_id"], projection.id)
        self.assertEqual(projection.external_version, 1)
        self.assertEqual(projection.partner_id.name, "Example Logistics")
        self.assertEqual(
            self.env["codestra.scrapper.projection.receipt"].sudo().search_count(
                [("tenant_id", "=", TENANT_ID)]
            ),
            1,
        )

    def test_same_event_with_different_content_is_rejected(self):
        self._apply(self._payload())
        conflicting = self._payload(company_name="Changed without a new event")
        with self.assertRaises(ValidationError):
            self._apply(conflicting)
        self.assertEqual(
            self.env["codestra.scrapper.projection.receipt"].sudo().search_count(
                [("tenant_id", "=", TENANT_ID)]
            ),
            1,
        )

    def test_update_stale_and_unchanged_version_paths(self):
        first = self._apply(self._payload())
        updated = self._payload(
            event_id="55555555-5555-4555-8555-555555555555",
            correlation_id="66666666-6666-4666-8666-666666666666",
            version=2,
            company_name="Example Logistics Updated",
        )
        update_result = self._apply(updated)
        self.assertEqual(update_result["result"], "updated")
        projection = self.env["codestra.scrapper.business"].sudo().browse(
            first["projection_id"]
        )
        self.assertEqual(projection.external_version, 2)
        self.assertEqual(projection.company_name, "Example Logistics Updated")

        unchanged = copy.deepcopy(updated)
        unchanged.update(
            {
                "event_id": "77777777-7777-4777-8777-777777777777",
                "correlation_id": "88888888-8888-4888-8888-888888888888",
            }
        )
        unchanged_result = self._apply(unchanged)
        self.assertEqual(unchanged_result["result"], "unchanged")

        stale = self._payload(
            event_id="99999999-9999-4999-8999-999999999999",
            correlation_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            version=1,
        )
        stale_result = self._apply(stale)
        self.assertEqual(stale_result["result"], "stale_ignored")
        self.assertEqual(projection.external_version, 2)
        self.assertEqual(projection.company_name, "Example Logistics Updated")

    def test_same_version_with_changed_projection_content_is_rejected(self):
        self._apply(self._payload())
        conflicting = self._payload(
            event_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            correlation_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
            company_name="Conflicting version one",
        )
        with self.assertRaises(ValidationError):
            self._apply(conflicting)
        self.assertFalse(
            self.env["codestra.scrapper.projection.receipt"].sudo().search(
                [("event_id", "=", conflicting["event_id"])],
                limit=1,
            )
        )

    def test_wrong_principal_and_unlisted_tenant_are_rejected(self):
        service_group = self.env.ref(
            "codestra_scrapper_projection.group_scrapper_projection_service"
        )
        wrong_user = self.env["res.users"].create(
            {
                "name": "Wrong Scrapper Service",
                "login": f"wrong-scrapper-{uuid.uuid4()}@example.invalid",
                "group_ids": [(6, 0, [service_group.id])],
            }
        )
        with self.assertRaises(AccessError):
            self.env["codestra.scrapper.business"].with_user(
                wrong_user
            ).apply_middleware_projection(self._payload())

        rogue_tenant = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
        with self.assertRaises(AccessError):
            self._apply(self._payload(tenant_id=rogue_tenant))
        self.assertFalse(
            self.env["codestra.scrapper.projection.receipt"].sudo().search([])
        )

    def test_direct_crud_and_finalized_receipt_mutation_are_blocked(self):
        result = self._apply(self._payload())
        projection = self.env["codestra.scrapper.business"].sudo().browse(
            result["projection_id"]
        )
        receipt = self.env["codestra.scrapper.projection.receipt"].sudo().search(
            [("event_id", "=", EVENT_ID)],
            limit=1,
        )
        with self.assertRaises(AccessError):
            projection.write({"company_name": "Bypass"})
        with self.assertRaises(AccessError):
            projection.unlink()
        with self.assertRaises(AccessError):
            receipt.write({"message": "Bypass"})
        with self.assertRaises(AccessError):
            receipt.unlink()
        with self.assertRaises(AccessError):
            self.env["codestra.scrapper.business"].sudo().create(
                {
                    "tenant_id": TENANT_ID,
                    "external_business_id": BUSINESS_ID,
                    "external_version": 1,
                    "company_name": "Bypass",
                    "last_event_id": EVENT_ID,
                    "last_projection_digest": "0" * 64,
                }
            )

    def test_payload_validation_is_fail_closed(self):
        invalid_payloads = [
            self._payload(confidence=1.1),
            self._payload(confidence=True),
            self._payload(country_code="DOM"),
            self._payload(projection_status="published"),
            self._payload(version=0),
            self._payload(website="ftp://example.invalid/file"),
            self._payload(source_url="https://user:secret@example.invalid/x"),
            self._payload(evidence_summary=["not", "an", "object"]),
            self._payload(tenant_id="not-a-uuid"),
            self._payload(company_name=""),
            self._payload(evidence_summary={"blob": "x" * 132_000}),
        ]
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValidationError):
                    self._apply(payload)
        self.assertFalse(
            self.env["codestra.scrapper.projection.receipt"].sudo().search([])
        )
