from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestCodestraClientContract(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.client = cls.env["res.partner"].create(
            {"name": "Client Company", "is_company": True}
        )
        cls.contact = cls.env["res.partner"].create(
            {"name": "Authorized Contact", "parent_id": cls.client.id}
        )

    def test_approval_requires_contact_and_sla(self):
        contract = self.env["codestra.client.contract"].create(
            {
                "client_id": self.client.id,
                "service_scope": "Inbound customer support",
            }
        )
        contract.action_submit()
        with self.assertRaises(ValidationError):
            contract.action_approve()
        contract.write(
            {
                "authorized_contact_ids": [Command.set([self.contact.id])],
                "sla_ids": [
                    Command.create(
                        {
                            "metric_code": "asa",
                            "name": "Average Speed of Answer",
                            "operator": "lte",
                            "target_value": 20,
                            "unit": "seconds",
                        }
                    )
                ],
            }
        )
        contract.action_approve()
        self.assertEqual(contract.state, "approved")
        next_version = contract.action_create_version()
        self.assertEqual(next_version.version, 2)
        self.assertEqual(next_version.predecessor_id, contract)
        self.assertEqual(next_version.state, "draft")
