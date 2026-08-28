from psycopg2 import IntegrityError

from odoo.tests.common import TransactionCase


class TestSchemaConstraints(TransactionCase):
    def test_odoo_19_constraints_are_enforced(self):
        event = self.env["codestra.integration.event"].register_event(
            "constraint.test", "odoo", "middleware", {}
        )
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env["codestra.integration.delivery"].create({
                "event_id": event.id,
                "attempt_number": 0,
                "destination": "logical-test",
            }).flush_recordset()
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env["codestra.integration.endpoint"].create({
                "name": "Invalid limits",
                "code": "invalid-limits",
                "direction": "outbound",
                "timeout_seconds": 0,
            }).flush_recordset()
