from pathlib import Path

from odoo.tests.common import TransactionCase

import odoo.addons.call_center_campaign as campaign_package


class TestControllerRegistration(TransactionCase):
    def test_module_initializer_registers_integration_controllers(self):
        initializer = Path(campaign_package.__file__).read_text(encoding="utf-8")

        self.assertIn("from . import controllers", initializer)

    def test_governed_outbox_does_not_alias_lead_ingestion_outbox(self):
        """Both installed addons must retain independent durable schemas."""
        if "codestra.integration.outbox" not in self.env:
            self.skipTest("lead-ingestion addon is not installed in this database")
        governed = self.env["codestra.runtime.integration.outbox"]
        ingestion = self.env["codestra.integration.outbox"]

        self.assertNotEqual(governed._name, ingestion._name)
        self.assertNotEqual(governed._table, ingestion._table)
        self.assertTrue(hasattr(governed, "_create_internal"))
        self.assertIn("record_environment", governed._fields)
        self.assertIn("batch_id", ingestion._fields)
