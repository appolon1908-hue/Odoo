from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestCodestraCcVicidialFacade(TransactionCase):
    def test_dependencies_are_installed(self):
        expected = {
            "codestra_cc_core",
            "codestra_cc_reliability",
            "codestra_vicidial_crm",
            "codestra_vicidial_connector",
            "codestra_telephony_bridge",
            "codestra_vicidial_recording",
        }
        modules = self.env["ir.module.module"].search([("name", "in", sorted(expected))])
        self.assertEqual(set(modules.mapped("name")), expected)
        self.assertEqual(set(modules.mapped("state")), {"installed"})
