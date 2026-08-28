from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestOmnichannelFacade(TransactionCase):
    def test_dependencies_are_installed(self):
        expected = {
            "codestra_cc_customer_360",
            "codestra_cc_compliance",
            "codestra_cc_reliability",
            "codestra_mail_inbox",
            "codestra_integration_hub",
        }
        modules = self.env["ir.module.module"].search([("name", "in", sorted(expected))])
        self.assertEqual(set(modules.mapped("name")), expected)
        self.assertEqual(set(modules.mapped("state")), {"installed"})
