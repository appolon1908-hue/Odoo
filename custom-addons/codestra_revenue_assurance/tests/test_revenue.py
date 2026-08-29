from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestCodestraRevenueAssurance(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        client = cls.env["res.partner"].create({"name": "Revenue Client", "is_company": True})
        cls.contract = cls.env["codestra.client.contract"].create(
            {
                "client_id": client.id,
                "service_scope": "Customer support",
                "state": "approved",
            }
        )

    def test_usage_snapshots_and_margin(self):
        plan = self.env["codestra.rate.plan"].create(
            {
                "name": "Per Interaction",
                "contract_id": self.contract.id,
                "billable_unit": "interaction",
                "client_unit_rate": 2.5,
                "provider_unit_cost": 0.75,
            }
        )
        plan.action_approve()
        plan.action_activate()
        usage = self.env["codestra.billing.usage"].create(
            {
                "rate_plan_id": plan.id,
                "source_system": "certification",
                "source_reference": "fixture-usage-1",
                "idempotency_key": "fixture-usage-idempotency-1",
                "units": 10,
            }
        )
        self.assertAlmostEqual(usage.revenue, 25.0, places=2)
        self.assertAlmostEqual(usage.provider_cost, 7.5, places=2)
        self.assertAlmostEqual(usage.margin, 17.5, places=2)
        usage.action_approve()
        self.assertEqual(usage.state, "approved")
