from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestAutomationFacade(TransactionCase):
    def test_dependencies_are_installed(self):
        expected = {
            "codestra_cc_reliability",
            "call_center_orchestration",
            "codestra_lead_automation",
            "codestra_social_orchestration",
            "codestra_integration_hub",
        }
        modules = self.env["ir.module.module"].search([("name", "in", sorted(expected))])
        self.assertEqual(set(modules.mapped("name")), expected)
        self.assertEqual(set(modules.mapped("state")), {"installed"})
