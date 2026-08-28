from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestComplianceFacade(TransactionCase):
    def test_dependencies_are_installed(self):
        expected = {
            "codestra_cc_security",
            "codestra_cc_crm",
            "codestra_cc_calls",
            "codestra_cc_recordings",
            "codestra_vicidial_crm",
            "call_center_compliance",
            "codestra_cc_audit",
        }
        modules = self.env["ir.module.module"].search([("name", "in", sorted(expected))])
        self.assertEqual(set(modules.mapped("name")), expected)
        self.assertEqual(set(modules.mapped("state")), {"installed"})
