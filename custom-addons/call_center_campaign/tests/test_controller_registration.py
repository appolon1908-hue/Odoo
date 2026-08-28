from pathlib import Path

from odoo.tests.common import TransactionCase

import odoo.addons.call_center_campaign as campaign_package


class TestControllerRegistration(TransactionCase):
    def test_module_initializer_registers_integration_controllers(self):
        initializer = Path(campaign_package.__file__).read_text(encoding="utf-8")

        self.assertIn("from . import controllers", initializer)

    def test_governed_outbox_does_not_alias_lead_ingestion_outbox(self):
        """Both addons retain distinct schemas regardless of module load order."""
        governed = self.env["codestra.runtime.integration.outbox"]
        ingestion_source = Path(
            "/mnt/extra-addons/codestra_lead_ingestion/models/import_models.py"
        ).read_text(encoding="utf-8")

        self.assertNotEqual(governed._name, "codestra.lead.import.outbox")
        self.assertNotEqual(governed._table, "codestra_lead_import_outbox")
        self.assertTrue(hasattr(governed, "_create_internal"))
        self.assertIn("record_environment", governed._fields)
        self.assertIn('_name = "codestra.lead.import.outbox"', ingestion_source)
        self.assertIn("batch_id = fields.Many2one", ingestion_source)
