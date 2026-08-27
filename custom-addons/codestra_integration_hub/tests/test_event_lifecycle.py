from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestEventLifecycle(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Event = self.env["codestra.integration.event"]

    def event(self):
        return self.Event.register_event("lead.changed", "odoo", "middleware", {"lead": 1})

    def test_happy_path_and_reverse_rejected(self):
        event = self.event()
        event.validate_event().queue_event().mark_processing().mark_processed()
        self.assertEqual(event.state, "processed")
        with self.assertRaises(ValidationError):
            event.mark_processing()

    def test_retry_and_ignored(self):
        event = self.event().validate_event().queue_event().mark_processing()
        event.schedule_retry("timeout", "bounded timeout")
        self.assertEqual(event.state, "retry")
        ignored = self.event().mark_ignored("not applicable")
        with self.assertRaises(ValidationError):
            ignored.schedule_retry()

    def test_retry_exhaustion_fails(self):
        event = self.event()
        event.max_attempts = 1
        event.validate_event().queue_event().mark_processing()
        event.schedule_retry("timeout", "terminal")
        self.assertEqual(event.state, "failed")
