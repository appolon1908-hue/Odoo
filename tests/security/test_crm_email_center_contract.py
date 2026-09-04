import ast
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "custom-addons" / "codestra_klyrow_smtp"


class TestCrmEmailCenterContract(unittest.TestCase):
    def test_manifest_registers_crm_and_local_backend_assets(self):
        manifest = ast.literal_eval((MODULE / "__manifest__.py").read_text(encoding="utf-8"))
        self.assertIn("crm", manifest["depends"])
        self.assertIn("codestra_cc_mail", manifest["depends"])
        assets = manifest["assets"]["web.assets_backend"]
        self.assertEqual(len(assets), 3)
        for asset in assets:
            self.assertTrue(asset.startswith("codestra_klyrow_smtp/"))
            self.assertTrue((MODULE.parent / asset).is_file())

    def test_normal_crm_action_and_menu_are_declared(self):
        tree = ET.parse(MODULE / "views" / "mail_routing_views.xml")
        action = tree.find(".//record[@id='action_crm_email_center']")
        menu = tree.find(".//menuitem[@id='menu_crm_email_center']")
        self.assertIsNotNone(action)
        self.assertIsNotNone(menu)
        self.assertEqual(menu.attrib["parent"], "crm.crm_menu_root")
        self.assertEqual(menu.attrib["action"], "action_crm_email_center")

    def test_popout_is_read_only_and_cannot_bypass_delivery(self):
        source = (MODULE / "static" / "src" / "js" / "crm_email_center_popout.js").read_text(
            encoding="utf-8"
        )
        template = (
            MODULE / "static" / "src" / "xml" / "crm_email_center_popout.xml"
        ).read_text(encoding="utf-8")
        server = (MODULE / "models" / "crm_email_center.py").read_text(encoding="utf-8")
        self.assertIn("crm_email_center_snapshot", source)
        self.assertIn("Compose locked", template)
        self.assertIn('"compose_enabled": False', server)
        for prohibited in ("mail.mail", "message_post(", ".send(", "send_mail("):
            self.assertNotIn(prohibited, source)


if __name__ == "__main__":
    unittest.main()
