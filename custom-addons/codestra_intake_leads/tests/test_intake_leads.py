from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCodestraIntakeLeads(TransactionCase):
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
        self.assertEqual(lead.codestra_tenant_id, "tenant-1")
        self.assertEqual(lead.codestra_campaign_key, "campaign-1")

        duplicate = self.env["crm.lead"].codestra_upsert_intake_lead(self._envelope())
        self.assertEqual(duplicate["action"], "duplicate")
        self.assertEqual(duplicate["lead_id"], lead.id)

    def test_same_tenant_matching_identity_updates_existing_lead(self):
        existing = self.env["crm.lead"].create(
            {
                "name": "Existing",
                "email_from": "ada@example.com",
                "codestra_tenant_id": "tenant-1",
            }
        )
        result = self.env["crm.lead"].codestra_upsert_intake_lead(
            self._envelope(event_id="lead-event-2", idempotency_key="idem-lead-2")
        )

        self.assertEqual(result["action"], "updated")
        self.assertEqual(result["lead_id"], existing.id)
        self.assertEqual(existing.codestra_intake_event_id, "lead-event-2")

    def test_different_tenant_does_not_reuse_existing_identity(self):
        existing = self.env["crm.lead"].create(
            {
                "name": "Other tenant",
                "email_from": "ada@example.com",
                "codestra_tenant_id": "tenant-2",
            }
        )
        result = self.env["crm.lead"].codestra_upsert_intake_lead(self._envelope())
        self.assertNotEqual(result["lead_id"], existing.id)

    def test_payload_tenant_mismatch_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.env["crm.lead"].codestra_upsert_intake_lead(
                self._envelope(tenantId="tenant-2")
            )
