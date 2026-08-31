import uuid

from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCodestraIntakeLeads(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        service_group = cls.env.ref("codestra_middleware_bridge.group_codestra_crm_api")
        cls.env.user.write({"group_ids": [(4, service_group.id)]})
        cls.env["ir.config_parameter"].sudo().set_param(
            "codestra.crm.tenant_ids",
            "tenant-1,tenant-2",
        )

    def _envelope(self, *, event_id="lead-event-1", idempotency_key="idem-lead-1", **payload_updates):
        payload = {
            "tenantId": "tenant-1",
            "siteId": "landing-1",
            "source": "landing_page",
            "campaignId": "campaign-1",
            "name": "Ada Example",
            "email": " ADA@EXAMPLE.COM ",
            "phone": "+1 (809) 555-0100",
            "message": "Please contact me",
            "attribution": {"campaign": "summer"},
            "consent": {"email": True},
            "fields": {"interest": "demo"},
            "metadata": {"landing": "summer-a"},
        }
        payload.update(payload_updates)
        return {
            "event_id": event_id,
            "event_type": "codestra.events.lead_submitted",
            "event_version": "1.0",
            "tenant_id": "tenant-1",
            "correlation_id": "corr-1",
            "idempotency_key": idempotency_key,
            "payload": payload,
        }

    def test_creates_normalized_lead_and_exact_retry_is_duplicate(self):
        result = self.env["crm.lead"].codestra_upsert_intake_lead(self._envelope())
        lead = self.env["crm.lead"].browse(result["lead_id"])
        self.assertEqual(result["action"], "created")
        self.assertEqual(lead.email_from, "ada@example.com")
        self.assertEqual(lead.phone, "+18095550100")
        duplicate = self.env["crm.lead"].codestra_upsert_intake_lead(self._envelope())
        self.assertEqual(duplicate["action"], "duplicate")
        self.assertEqual(duplicate["lead_id"], lead.id)

    def test_non_service_identity_is_rejected_before_privileged_receipt_access(self):
        user = self.env["res.users"].create({
            "name": "Unauthorized Intake User",
            "login": f"unauthorized-intake-{uuid.uuid4()}@example.invalid",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        with self.assertRaises(AccessError):
            self.env["crm.lead"].with_user(user).codestra_upsert_intake_lead(self._envelope())
        self.assertFalse(
            self.env["codestra.intake.receipt"].sudo().search(
                [("event_id", "=", "lead-event-1")]
            )
        )

    def test_unlisted_tenant_is_rejected(self):
        envelope = self._envelope()
        envelope["tenant_id"] = "tenant-rogue"
        envelope["payload"]["tenantId"] = "tenant-rogue"
        with self.assertRaises(AccessError):
            self.env["crm.lead"].codestra_upsert_intake_lead(envelope)

    def test_prior_event_receipt_survives_later_update(self):
        first = self.env["crm.lead"].codestra_upsert_intake_lead(self._envelope())
        second = self.env["crm.lead"].codestra_upsert_intake_lead(
            self._envelope(event_id="lead-event-2", idempotency_key="idem-lead-2", message="Newer message")
        )
        self.assertEqual(second["lead_id"], first["lead_id"])
        replay = self.env["crm.lead"].codestra_upsert_intake_lead(self._envelope())
        self.assertEqual(replay["action"], "duplicate")
        self.assertEqual(replay["lead_id"], first["lead_id"])
        self.assertEqual(
            self.env["codestra.intake.receipt"].sudo().search_count([("tenant_id", "=", "tenant-1")]),
            2,
        )

    def test_receipt_survives_lead_deletion_and_still_blocks_replay(self):
        first = self.env["crm.lead"].codestra_upsert_intake_lead(
            self._envelope(event_id="lead-delete-1", idempotency_key="idem-delete-1")
        )
        self.env["crm.lead"].sudo().browse(first["lead_id"]).unlink()
        receipt = self.env["codestra.intake.receipt"].sudo().search(
            [("event_id", "=", "lead-delete-1")],
            limit=1,
        )
        self.assertTrue(receipt)
        self.assertFalse(receipt.lead_id)
        replay = self.env["crm.lead"].codestra_upsert_intake_lead(
            self._envelope(event_id="lead-delete-1", idempotency_key="idem-delete-1")
        )
        self.assertEqual(replay["action"], "duplicate")
        self.assertFalse(replay["lead_id"])

    def test_omitted_optional_fields_do_not_clear_existing_values(self):
        existing = self.env["crm.lead"].create({
            "name": "Existing",
            "contact_name": "Existing Person",
            "email_from": "ada@example.com",
            "phone": "+18095550100",
            "description": "Keep me",
            "codestra_tenant_id": "tenant-1",
            "codestra_source_channel": "voice",
            "codestra_intake_metadata": {
                "fields": {"existing": "field"},
                "metadata": {"existing": "metadata"},
            },
        })
        envelope = self._envelope(event_id="lead-event-3", idempotency_key="idem-lead-3")
        for key in ("name", "phone", "message", "source", "fields", "metadata"):
            envelope["payload"].pop(key)
        result = self.env["crm.lead"].codestra_upsert_intake_lead(envelope)
        self.assertEqual(result["lead_id"], existing.id)
        self.assertEqual(existing.contact_name, "Existing Person")
        self.assertEqual(existing.phone, "+18095550100")
        self.assertEqual(existing.description, "Keep me")
        self.assertEqual(existing.codestra_source_channel, "voice")
        self.assertEqual(
            existing.codestra_intake_metadata,
            {"fields": {"existing": "field"}, "metadata": {"existing": "metadata"}},
        )

    def test_partial_metadata_update_preserves_omitted_component(self):
        existing = self.env["crm.lead"].create({
            "name": "Existing",
            "email_from": "ada@example.com",
            "codestra_tenant_id": "tenant-1",
            "codestra_intake_metadata": {
                "fields": {"old": "field"},
                "metadata": {"keep": "yes"},
            },
        })
        envelope = self._envelope(
            event_id="lead-meta-1",
            idempotency_key="idem-meta-1",
            fields={"new": "field"},
        )
        envelope["payload"].pop("metadata")
        result = self.env["crm.lead"].codestra_upsert_intake_lead(envelope)
        self.assertEqual(result["lead_id"], existing.id)
        self.assertEqual(
            existing.codestra_intake_metadata,
            {"fields": {"new": "field"}, "metadata": {"keep": "yes"}},
        )

    def test_transcript_only_update_persists_description(self):
        existing = self.env["crm.lead"].create({
            "name": "Existing",
            "email_from": "ada@example.com",
            "description": "Old description",
            "codestra_tenant_id": "tenant-1",
        })
        envelope = self._envelope(
            event_id="lead-transcript-1",
            idempotency_key="idem-transcript-1",
            transcript="Agent and visitor conversation",
        )
        envelope["payload"].pop("message")
        result = self.env["crm.lead"].codestra_upsert_intake_lead(envelope)
        self.assertEqual(result["lead_id"], existing.id)
        self.assertIn("Agent and visitor conversation", existing.description)

    def test_formatted_phone_matches_normalized_phone(self):
        existing = self.env["crm.lead"].create({
            "name": "Existing",
            "phone": "+1 (809) 555-0100",
            "codestra_tenant_id": "tenant-1",
        })
        envelope = self._envelope(event_id="lead-event-4", idempotency_key="idem-lead-4", email=None)
        result = self.env["crm.lead"].codestra_upsert_intake_lead(envelope)
        self.assertEqual(result["lead_id"], existing.id)

    def test_identifiers_are_canonicalized_before_receipt_storage(self):
        envelope = self._envelope()
        envelope["event_id"] = " lead-event-space "
        envelope["idempotency_key"] = " idem-space "
        first = self.env["crm.lead"].codestra_upsert_intake_lead(envelope)
        retry = self._envelope(event_id="lead-event-space", idempotency_key="idem-space")
        duplicate = self.env["crm.lead"].codestra_upsert_intake_lead(retry)
        self.assertEqual(duplicate["action"], "duplicate")
        self.assertEqual(duplicate["lead_id"], first["lead_id"])

    def test_different_tenant_does_not_reuse_existing_identity(self):
        existing = self.env["crm.lead"].create({
            "name": "Other tenant",
            "email_from": "ada@example.com",
            "codestra_tenant_id": "tenant-2",
        })
        result = self.env["crm.lead"].codestra_upsert_intake_lead(self._envelope())
        lead = self.env["crm.lead"].browse(result["lead_id"])
        self.assertNotEqual(lead.id, existing.id)
        self.assertEqual(lead.codestra_tenant_id, "tenant-1")
        self.assertEqual(existing.codestra_tenant_id, "tenant-2")

    def test_payload_tenant_mismatch_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.env["crm.lead"].codestra_upsert_intake_lead(self._envelope(tenantId="tenant-2"))
