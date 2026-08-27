from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestCustomer360Facade(TransactionCase):
    def test_dependencies_are_installed(self):
        expected = {"codestra_cc_core", "codestra_interaction_workflow", "codestra_mail_inbox", "crm", "contacts", "mail"}
        modules = self.env["ir.module.module"].search([("name", "in", sorted(expected))])
        self.assertEqual(set(modules.mapped("name")), expected)
        self.assertEqual(set(modules.mapped("state")), {"installed"})
