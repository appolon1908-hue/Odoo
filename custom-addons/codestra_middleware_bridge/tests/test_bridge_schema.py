from odoo.tests.common import TransactionCase
from psycopg2 import IntegrityError


class TestBridgeSchema(TransactionCase):
    def test_external_identity_uniqueness_belongs_to_partner(self):
        external_id = "synthetic-contact-identity"
        self.env["res.partner"].create({
            "name": "Synthetic Contact One",
            "codestra_integration_external_id": external_id,
        })
        with self.assertRaises(IntegrityError):
            self.env["res.partner"].create({
                "name": "Synthetic Contact Two",
                "codestra_integration_external_id": external_id,
            })

    def test_crm_lead_registry_has_no_partner_only_constraint(self):
        lead = self.env["crm.lead"].create({"name": "Synthetic CRM Lead"})
        self.assertTrue(lead.exists())
