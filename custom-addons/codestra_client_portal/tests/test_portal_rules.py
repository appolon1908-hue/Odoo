from odoo import Command
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestCodestraClientPortalRules(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.client = cls.env["res.partner"].create({"name": "Portal Client", "is_company": True})
        cls.other_client = cls.env["res.partner"].create({"name": "Other Client", "is_company": True})
        contact = cls.env["res.partner"].create({"name": "Portal User", "parent_id": cls.client.id})
        portal_group = cls.env.ref("base.group_portal")
        cls.portal_user = cls.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": "Portal User",
                "login": "codestra-portal-fixture@example.test",
                "email": "codestra-portal-fixture@example.test",
                "partner_id": contact.id,
                "share": True,
                "group_ids": [Command.set([portal_group.id])],
            }
        )
        cls.own_contract = cls.env["codestra.client.contract"].create(
            {"client_id": cls.client.id, "service_scope": "Owned contract"}
        )
        cls.other_contract = cls.env["codestra.client.contract"].create(
            {"client_id": cls.other_client.id, "service_scope": "Other contract"}
        )

    def test_portal_user_sees_only_commercial_partner_contracts(self):
        visible = self.env["codestra.client.contract"].with_user(self.portal_user).search([])
        self.assertIn(self.own_contract, visible)
        self.assertNotIn(self.other_contract, visible)
