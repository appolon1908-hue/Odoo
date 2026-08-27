from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestDisabledDelivery(TransactionCase):
    def test_defaults_cron_and_delivery_fail_closed(self):
        endpoint = self.env["codestra.integration.endpoint"].create({"name": "Logical test", "code": "logical-test", "direction": "outbound"})
        self.assertFalse(endpoint.enabled)
        self.assertTrue(endpoint.test_only)
        self.assertNotIn("secret_reference", endpoint._fields)
        self.assertFalse(any(
            marker in field_name.lower()
            for field_name in endpoint._fields
            for marker in ("password", "credential", "secret", "token")
        ))
        with self.assertRaises(ValidationError):
            endpoint.perform_connectivity_test()
        with self.assertRaises(ValidationError):
            self.env["codestra.integration.delivery"].perform_delivery()
        cron = self.env.ref("codestra_integration_hub.cron_retry_eligibility_report")
        self.assertFalse(cron.active)

    def test_delivery_attempt_is_ledger_only(self):
        event = self.env["codestra.integration.event"].register_event(
            "delivery.test", "odoo", "middleware", {}
        )
        attempt = self.env["codestra.integration.delivery"].create({
            "event_id": event.id,
            "attempt_number": 1,
            "destination": "logical-test",
            "state": "failed",
            "error_code": "disabled",
        })
        self.assertEqual(attempt.state, "failed")
        self.assertEqual(event.delivery_ids, attempt)
        self.assertEqual(event.attempt_count, 0)
