from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase


class TestAudit(TransactionCase):
    def test_append_only_chain_and_tamper_detection(self):
        event = self.env["codestra.integration.event"].register_event("x", "odoo", "middleware", {})
        event.validate_event()
        audit = self.env["codestra.integration.audit"].search([("event_id", "=", event.id)])
        self.assertTrue(audit.verify_chain())
        self.assertNotIn("secret-value", audit.metadata_redacted or "")
        with self.assertRaises(AccessError):
            audit.write({"action": "tampered"})
        with self.assertRaises(AccessError):
            audit.unlink()
        self.env.cr.execute("UPDATE codestra_integration_audit SET record_hash='tampered' WHERE id=%s", [audit.id])
        self.env.invalidate_all()
        with self.assertRaises(ValidationError):
            audit.verify_chain()
