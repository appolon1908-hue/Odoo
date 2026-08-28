from odoo.tests.common import TransactionCase

from ..models.res_config_settings import FLAG_NAMES, ResConfigSettings


class TestFeatureFlags(TransactionCase):
    def test_flags_fail_closed(self):
        params = self.env["ir.config_parameter"].sudo()
        for name in FLAG_NAMES:
            params.search([("key", "=", f"codestra.{name}")]).unlink()
            self.assertFalse(self.env["codestra.feature.flags"].flag_enabled(name))
            params.set_param(f"codestra.{name}", "not-a-boolean")
            self.assertFalse(self.env["codestra.feature.flags"].flag_enabled(name))
            params.set_param(f"codestra.{name}", "true")
            self.assertTrue(self.env["codestra.feature.flags"].flag_enabled(name))
            params.set_param(f"codestra.{name}", "false")

    def test_unknown_flag_is_false(self):
        self.assertFalse(self.env["codestra.feature.flags"].flag_enabled("unknown"))

    def test_enabling_one_flag_does_not_enable_another(self):
        params = self.env["ir.config_parameter"].sudo()
        params.search([("key", "in", [f"codestra.{name}" for name in FLAG_NAMES])]).unlink()
        selected = "n8n_delivery_enabled"
        params.set_param(f"codestra.{selected}", "true")

        for name in FLAG_NAMES:
            self.assertEqual(
                self.env["codestra.feature.flags"].flag_enabled(name),
                name == selected,
                f"feature flag isolation failed for {name}",
            )

        params.set_param(f"codestra.{selected}", "false")
