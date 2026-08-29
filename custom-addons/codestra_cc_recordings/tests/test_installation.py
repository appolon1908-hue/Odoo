from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestRecordingGovernanceInstallation(TransactionCase):
    def test_dependencies_and_safety_flags(self):
        expected = {
            "codestra_cc_calls",
            "codestra_cc_vicidial",
            "codestra_vicidial_recording",
        }
        modules = self.env["ir.module.module"].search(
            [("name", "in", sorted(expected))]
        )
        self.assertEqual(set(modules.mapped("name")), expected)
        self.assertEqual(set(modules.mapped("state")), {"installed"})
        params = self.env["ir.config_parameter"].sudo()
        self.assertEqual(
            params.get_param("CC_ENABLE_RECORDING_PLAYBACK", "false"), "false"
        )
        self.assertEqual(params.get_param("CC_ENABLE_AI_ASSIST", "false"), "false")
