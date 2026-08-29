from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCompliance(TransactionCase):
    def setUp(self):
        super().setUp()
        self.unit = self.env.ref("call_center_core.business_unit_transport")
        self.campaign = self.env.ref(
            "call_center_campaign.campaign_moy_carrier_out"
        )

    def test_dnc_fails_closed(self):
        lead = self.env["crm.lead"].create(
            {"name": "DNC", "business_unit_id": self.unit.id,
             "call_center_campaign_id": self.campaign.id,
             "phone": "+18095550100", "do_not_call": True}
        )
        lead.action_check_contact_eligibility()
        self.assertEqual(lead.contact_eligibility, "blocked")
        with self.assertRaises(ValidationError):
            lead.assert_contact_allowed()

    def test_suppression_hash_blocks_without_plain_identifier(self):
        lead = self.env["crm.lead"].create(
            {"name": "Suppressed", "business_unit_id": self.unit.id,
             "call_center_campaign_id": self.campaign.id,
             "phone": "+18095550101"}
        )
        digest = self.env["call.center.suppression"].hash_identifier(
            lead.normalized_phone
        )
        self.env["call.center.suppression"].create(
            {"business_unit_id": self.unit.id, "identifier_type": "phone",
             "identifier_hash": digest, "reason": "dnc", "source": "test"}
        )
        lead.action_check_contact_eligibility()
        self.assertEqual(lead.contact_eligibility, "blocked")
