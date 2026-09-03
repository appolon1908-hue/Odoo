from odoo.tests.common import TransactionCase


class TestCodestraMarketingCRM(TransactionCase):
    def test_marketing_attribution_fields_exist(self):
        fields = self.env["crm.lead"]._fields
        for name in (
            "codestra_marketing_tenant_id",
            "codestra_marketing_lead_id",
            "codestra_provider",
            "codestra_provider_campaign_id",
            "codestra_provider_adset_id",
            "codestra_provider_ad_id",
            "codestra_click_id",
            "codestra_conversion_status",
        ):
            self.assertIn(name, fields)

    def test_marketing_lead_identity_is_tenant_scoped(self):
        Lead = self.env["crm.lead"]
        Lead.create({
            "name": "Lead A",
            "codestra_marketing_tenant_id": "tenant-a",
            "codestra_marketing_lead_id": "lead-1",
        })
        Lead.create({
            "name": "Lead B",
            "codestra_marketing_tenant_id": "tenant-b",
            "codestra_marketing_lead_id": "lead-1",
        })
        self.assertEqual(Lead.search_count([("codestra_marketing_lead_id", "=", "lead-1")]), 2)
