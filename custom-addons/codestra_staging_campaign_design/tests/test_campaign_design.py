from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestCampaignDesign(TransactionCase):
    def test_all_designs_and_extension_pools_are_disabled(self):
        profiles = self.env["codestra.campaign.design.profile"].with_context(active_test=False).search([])
        self.assertEqual(set(profiles.mapped("code")), {"MOY-R1", "MBL-R1", "COD-R1", "SCP-R1", "STU-R1", "B4S-R1", "QA-R1"})
        self.assertFalse(any(profiles.mapped("active")))
        pools = self.env["codestra.extension.pool"].with_context(active_test=False).search([("code", "in", ["MOY-6100", "MBL-6200", "COD-6300", "SCP-6400", "STU-6500", "QA-6900"])])
        self.assertEqual(len(pools), 6)
        self.assertFalse(any(pools.mapped("active")))

    def test_each_campaign_has_nine_deterministic_dispositions(self):
        for profile in self.env["codestra.campaign.design.profile"].with_context(active_test=False).search([]):
            rows = self.env["codestra.disposition"].with_context(active_test=False).search([("campaign_id", "=", profile.campaign_id.id)])
            self.assertEqual(set(rows.mapped("vicidial_status_code")), {"ANSWERED", "SALE", "NOT_INTERESTED", "CALLBACK", "BUSY", "NO_ANSWER", "DISCONNECTED", "DNC", "WRONG_NUMBER"})
            self.assertFalse(any(rows.mapped("active")))

    def test_dnc_and_missing_required_fields_fail_closed(self):
        profile = self.env.ref("codestra_staging_campaign_design.design_b4s")
        with self.assertRaises(ValidationError):
            self.env["crm.lead"].create({"name": "Synthetic", "business_unit_id": profile.business_unit_id.id, "campaign_design_id": profile.id, "contact_permission": "dnc", "consent_evidence_reference": "synthetic"})
