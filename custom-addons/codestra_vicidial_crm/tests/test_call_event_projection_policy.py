from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase


class TestCallEventProjectionPolicy(TransactionCase):
    def setUp(self):
        super().setUp()
        self.params = self.env["ir.config_parameter"].sudo()
        self.policy = self.env["codestra.call.event.projection.policy"].sudo()
        self.params.set_param("codestra.call_event_projection_enabled", "False")
        self.params.set_param("codestra.call_event_synthetic_only", "True")
        self.params.set_param("codestra.call_event_activation_reference", "")
        self.flag = self.env["call.center.feature.flag"].sudo().search(
            [("code", "=", "ENABLE_WEBSOCKET_SCREEN_POP")], limit=1
        )
        self.flag.write({"enabled": False})

    def test_projection_is_disabled_by_default(self):
        with self.assertRaises(AccessError):
            self.policy.authorize_payload(
                {"synthetic_test": True, "campaign_id": "TEST_SYN"}
            )
        self.assertFalse(self.policy.screen_pop_enabled())

    def test_synthetic_event_requires_enablement(self):
        self.params.set_param("codestra.call_event_projection_enabled", "True")
        self.assertTrue(
            self.policy.authorize_payload(
                {"synthetic_test": True, "campaign_id": "TEST_SYN"}
            )
        )
        with self.assertRaises(AccessError):
            self.policy.authorize_payload(
                {"synthetic_test": False, "campaign_id": "COD-SALES-OUT"}
            )

    def test_non_synthetic_requires_activation_reference(self):
        self.params.set_param("codestra.call_event_projection_enabled", "True")
        self.params.set_param("codestra.call_event_synthetic_only", "False")
        with self.assertRaises(AccessError):
            self.policy.authorize_payload(
                {"synthetic_test": False, "campaign_id": "COD-SALES-OUT"}
            )
        self.params.set_param(
            "codestra.call_event_activation_reference",
            "CHG-20260904-CALL-EVENTS-01",
        )
        self.assertTrue(
            self.policy.authorize_payload(
                {"synthetic_test": False, "campaign_id": "COD-SALES-OUT"}
            )
        )

    def test_screen_pop_requires_separate_feature_flag(self):
        self.params.set_param("codestra.call_event_projection_enabled", "True")
        self.assertFalse(self.policy.screen_pop_enabled())
        self.flag.write(
            {"enabled": True, "environment": "staging", "activation_reference": False}
        )
        self.assertTrue(self.policy.screen_pop_enabled())
