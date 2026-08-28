from odoo.tests.common import TransactionCase


class TestInteractionDashboard(TransactionCase):
    def test_snapshot_is_an_orm_read_model(self):
        snapshot = self.env["codestra.integration.dashboard"].get_dashboard_snapshot()
        self.assertIn("cards", snapshot)
        self.assertIn("pending_outbox", snapshot["cards"])

    def test_production_activation_request_is_rejected(self):
        with self.assertRaises(Exception):
            self.env["codestra.integration.dashboard"].request_workflow_activation(
                "codestra.test.workflow", "1.0.0", "PRODUCTION", "test"
            )
