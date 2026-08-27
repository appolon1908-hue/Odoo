from odoo.tests.common import TransactionCase


class TestIdempotency(TransactionCase):
    def test_call_event_key_is_unique(self):
        values = {"event_type": "test", "idempotency_key": "call-event-test"}
        self.env["codestra.vicidial.call.event"].create(values)
        with self.assertRaises(Exception):
            self.env["codestra.vicidial.call.event"].create(values)
