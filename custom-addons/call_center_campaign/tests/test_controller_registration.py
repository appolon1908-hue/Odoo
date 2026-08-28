from pathlib import Path

from odoo.tests.common import TransactionCase

import odoo.addons.call_center_campaign as campaign_package


class TestControllerRegistration(TransactionCase):
    def test_module_initializer_registers_integration_controllers(self):
        initializer = Path(campaign_package.__file__).read_text(encoding="utf-8")

        self.assertIn("from . import controllers", initializer)

    def test_governed_outbox_does_not_alias_lead_ingestion_outbox(self):
        """The reverse-dependent add-on must retain an independent schema."""
        governed = self.env["codestra.runtime.integration.outbox"]
        addon_root = Path(campaign_package.__file__).parents[1]
        ingestion_source = (
            addon_root / "codestra_lead_ingestion" / "models" / "import_models.py"
        ).read_text(encoding="utf-8")

        self.assertEqual(governed._name, "codestra.runtime.integration.outbox")
        self.assertNotEqual(governed._name, "codestra.lead.import.outbox")
        self.assertTrue(hasattr(governed, "_create_internal"))
        self.assertIn("record_environment", governed._fields)
        self.assertIn('_name = "codestra.lead.import.outbox"', ingestion_source)
        self.assertIn("batch_id = fields.Many2one", ingestion_source)
