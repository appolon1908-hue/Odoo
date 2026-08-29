from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase


class TestOfflineConnector(TransactionCase):
    def setUp(self):
        super().setUp()
        self.profile = self.env["codestra.vicidial.connector.profile"].create({"name": "TEST_SYN"})

    def test_profile_is_fail_closed(self):
        self.assertFalse(self.profile.active)
        self.assertTrue(self.profile.test_only)
        self.assertEqual(self.profile.adapter_type, "test_syn")
        with self.assertRaises(ValidationError):
            self.profile.write({"active": True})

    def test_preview_is_deterministic_and_redacted(self):
        sensitive_value = "must-not-persist"
        records = [{"record_type": "lead", "external_reference": "TEST_SYN_1", "payload": {"phone": "15550000000", "status": "NEW", "password": sensitive_value}}]
        first = self.env["codestra.vicidial.connector.import.batch"].create({"profile_id": self.profile.id})
        second = self.env["codestra.vicidial.connector.import.batch"].create({"profile_id": self.profile.id})
        first.preview(records)
        second.preview(records)
        self.assertEqual(first.source_fingerprint, second.source_fingerprint)
        self.assertNotIn(sensitive_value, first.line_ids.normalized_json)
        self.assertEqual(first.record_count, 1)
        first.validate_preview()
        self.assertEqual(first.state, "validated")

    def test_live_apply_is_unavailable(self):
        batch = self.env["codestra.vicidial.connector.import.batch"].create({"profile_id": self.profile.id})
        with self.assertRaises(AccessError):
            batch.apply_import()

    def test_invalid_input_rejected(self):
        batch = self.env["codestra.vicidial.connector.import.batch"].create({"profile_id": self.profile.id})
        with self.assertRaises(ValidationError):
            batch.preview([{"record_type": "unknown", "external_reference": "x", "payload": {}}])
