from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestAnalyticsFacade(TransactionCase):
    def test_dependencies_are_installed(self):
        expected = {
            "codestra_analytics_reporting",
            "codestra_daily_reporting",
            "codestra_revenue_assurance",
            "codestra_cc_workforce",
            "codestra_cc_quality",
            "codestra_cc_omnichannel",
        }
        modules = self.env["ir.module.module"].search([("name", "in", sorted(expected))])
        self.assertEqual(set(modules.mapped("name")), expected)
        self.assertEqual(set(modules.mapped("state")), {"installed"})
