from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestMailboxFacade(TransactionCase):
    def test_dependencies_are_installed(self):
        expected = {
            "codestra_cc_identity",
            "codestra_cc_campaign",
            "codestra_identity_provisioning",
            "codestra_mail_inbox",
        }
        modules = self.env["ir.module.module"].search([("name", "in", sorted(expected))])
        self.assertEqual(set(modules.mapped("name")), expected)
        self.assertEqual(set(modules.mapped("state")), {"installed"})
