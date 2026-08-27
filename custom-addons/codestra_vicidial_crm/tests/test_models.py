from odoo.tests.common import TransactionCase


class TestCodestraModels(TransactionCase):
    def test_default_disposition_and_idempotency(self):
        self.assertTrue(self.env["codestra.vicidial.disposition"].search([("code", "=", "NEW")]))
        event = self.env["codestra.integration.event"].create(
            {"event_type": "test", "idempotency_key": "test-key", "payload_hash": "a"}
        )
        with self.assertRaises(Exception):
            self.env["codestra.integration.event"].create(
                {"event_type": "test", "idempotency_key": "test-key", "payload_hash": "a"}
            )
        self.assertEqual(event.state, "new")

    def test_flags_are_safe_by_default(self):
        params = self.env["ir.config_parameter"].sudo()
        self.assertNotEqual(params.get_param("codestra.live_writes_enabled", "false"), "true")
        self.assertNotEqual(params.get_param("codestra.vicidial_read_only", "true"), "false")
