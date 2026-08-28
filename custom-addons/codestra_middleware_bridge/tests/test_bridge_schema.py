from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError
from psycopg2 import IntegrityError


class TestBridgeSchema(TransactionCase):
    def test_middleware_target_requires_credential_free_https(self):
        client = self.env["codestra.middleware.outbound"]
        valid = "https://middleware.example.test/api/v1/events"
        self.assertEqual(client._validated_target(valid), valid)
        for unsafe in (
            "http://middleware.example.test/api/v1/events",
            "https://user:secret@middleware.example.test/api/v1/events",
            "https://middleware.example.test/api/v1/events?redirect=1",
        ):
            with self.subTest(unsafe=unsafe), self.assertRaises(ValidationError):
                client._validated_target(unsafe)

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
