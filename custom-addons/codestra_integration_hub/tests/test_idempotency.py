from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase


class TestIdempotency(TransactionCase):
    def test_replay_and_conflict(self):
        ledger = self.env["codestra.integration.idempotency"]
        args = ("lead", "raw-key-never-stored", "lead.changed", "odoo", "middleware")
        first = ledger.register_idempotent_event(*args, {"a": 1}, "corr-1")
        replay = ledger.register_idempotent_event(*args, {"a": 1}, "corr-1")
        conflict = ledger.register_idempotent_event(*args, {"a": 2}, "corr-1")
        self.assertTrue(first["created"])
        self.assertTrue(replay["replay"])
        self.assertTrue(conflict["conflict"])
        self.assertEqual(first["event"], replay["event"])
        self.assertEqual(ledger.search_count([("scope", "=", "lead")]), 1)
        self.assertFalse(ledger.search([("name", "ilike", "raw-key-never-stored")]))
        record = ledger.search([("scope", "=", "lead")])
        self.assertEqual(record.conflict_count, 1)
        with self.assertRaises(AccessError):
            record.write({"result_reference": "changed"})
        with self.assertRaises(AccessError):
            record.unlink()
