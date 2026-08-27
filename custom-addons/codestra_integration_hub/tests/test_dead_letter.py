from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase


class TestDeadLetter(TransactionCase):
    def test_dead_letter_and_replay_marker_only(self):
        event = self.env["codestra.integration.event"].register_event("x", "odoo", "middleware", {})
        event.validate_event().queue_event().mark_processing().mark_failed("terminal", "failed")
        event.move_to_dead_letter("terminal", "failed")
        dead = event.dead_letter_id
        self.assertEqual(event.state, "dead_letter")
        dead.request_replay()
        self.assertTrue(dead.replay_requested)
        self.assertFalse(self.env["codestra.integration.delivery"].search_count([("event_id", "=", event.id)]))
        dead.resolve("reviewed", "No replay performed")
        self.assertTrue(dead.resolved)
        self.assertTrue(self.env["codestra.integration.audit"].search_count([
            ("event_id", "=", event.id), ("action", "=", "dead_letter.resolved")
        ]))
        with self.assertRaises(AccessError):
            dead.unlink()
