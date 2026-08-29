from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestDataQualityModelCompatibility(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env["call.center.business.unit"].create(
            {"name": "DQ Compatibility Unit", "code": "DQ-COMPAT"}
        )
        cls.campaign = cls.env["call.center.campaign"].create(
            {
                "name": "DQ Compatibility Campaign",
                "code": "DQ-COMPAT-CAMPAIGN",
                "business_unit_id": cls.unit.id,
            }
        )
        cls.lead = cls.env["crm.lead"].create(
            {
                "name": "DQ Compatibility Lead",
                "business_unit_id": cls.unit.id,
                "call_center_campaign_id": cls.campaign.id,
            }
        )

    def test_canonical_and_campaign_fields_coexist(self):
        field_names = set(self.env["codestra.data.quality.issue"]._fields)
        self.assertTrue(
            {
                "res_model",
                "res_id",
                "duplicate_res_id",
                "severity",
                "issue_uuid",
                "campaign_id",
                "lead_id",
                "safe_detail",
                "correlation_id",
            }
            <= field_names
        )

    def test_legacy_values_normalize_and_target_the_lead(self):
        issue = self.env["codestra.data.quality.issue"].create(
            {
                "issue_type": "INVALID_PHONE",
                "state": "OPEN",
                "lead_id": self.lead.id,
            }
        )
        self.assertEqual(issue.issue_type, "invalid_phone")
        self.assertEqual(issue.state, "open")
        self.assertEqual(issue.res_model, "crm.lead")
        self.assertEqual(issue.res_id, self.lead.id)
        self.assertEqual(issue.campaign_id, self.campaign)
        self.assertEqual(issue.company_id, self.unit.company_id)
        self.assertTrue(issue.issue_uuid)
        self.assertTrue(issue.correlation_id)

    def test_campaign_only_legacy_issue_uses_company_partner_target(self):
        issue = self.env["codestra.data.quality.issue"].create(
            {
                "issue_type": "STALE_LEAD",
                "campaign_id": self.campaign.id,
            }
        )
        self.assertEqual(issue.issue_type, "stale_lead")
        self.assertEqual(issue.res_model, "res.partner")
        self.assertEqual(issue.res_id, self.unit.company_id.partner_id.id)
        self.assertEqual(issue.company_id, self.unit.company_id)
