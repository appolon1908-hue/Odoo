from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLeadValidation(TransactionCase):
    def setUp(self):
        super().setUp()
        self.unit = self.env.ref("call_center_core.business_unit_transport")
        self.campaign = self.env.ref(
            "call_center_campaign.campaign_moy_carrier_out"
        )

    def test_normalization_and_duplicate_detection(self):
        first = self.env["crm.lead"].create(
            {"name": "First", "business_unit_id": self.unit.id,
             "call_center_campaign_id": self.campaign.id,
             "phone": "(809) 555-0100", "email_from": "TEST@EXAMPLE.COM"}
        )
        second = self.env["crm.lead"].create(
            {"name": "Second", "business_unit_id": self.unit.id,
             "call_center_campaign_id": self.campaign.id,
             "phone": "809-555-0100"}
        )
        first.action_validate_lead()
        second.action_validate_lead()
        self.assertEqual(first.normalized_email, "test@example.com")
        self.assertEqual(second.validation_state, "duplicate")
        self.assertTrue(second.duplicate_candidate_ids)

    def test_invalid_email_is_rejected(self):
        lead = self.env["crm.lead"].create(
            {"name": "Invalid", "business_unit_id": self.unit.id,
             "call_center_campaign_id": self.campaign.id,
             "email_from": "not-an-email"}
        )
        lead.action_validate_lead()
        self.assertEqual(lead.validation_state, "invalid")
        self.assertIn("invalid_email", lead.validation_errors)
