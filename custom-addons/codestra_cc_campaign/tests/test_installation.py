from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestCampaignFacade(TransactionCase):
    def test_dependencies_are_installed(self):
        expected = {"codestra_cc_core", "call_center_campaign", "codestra_campaign_crm_os", "codestra_staging_campaign_design"}
        modules = self.env["ir.module.module"].search([("name", "in", sorted(expected))])
        self.assertEqual(set(modules.mapped("name")), expected)
        self.assertEqual(set(modules.mapped("state")), {"installed"})
