from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestWebRTCAssignment(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Agent = cls.env["codestra.vicidial.agent"]
        cls.user_one = cls.env["res.users"].create(
            {"name": "WebRTC One", "login": "webrtc-one@example.test"}
        )
        cls.user_two = cls.env["res.users"].create(
            {"name": "WebRTC Two", "login": "webrtc-two@example.test"}
        )

    def test_agent_without_webrtc_needs_no_extension(self):
        agent = self.Agent.create(
            {
                "name": "No WebRTC",
                "vicidial_user": "NOWEBRTC",
                "odoo_user_id": self.user_one.id,
                "webrtc_enabled": False,
            }
        )
        self.assertFalse(agent.phone_login)

    def test_webrtc_requires_exactly_one_extension(self):
        with self.assertRaises(ValidationError):
            self.Agent.create(
                {
                    "name": "Missing extension",
                    "vicidial_user": "NOEXT",
                    "odoo_user_id": self.user_one.id,
                    "webrtc_enabled": True,
                }
            )

    def test_extension_forbidden_when_webrtc_disabled(self):
        with self.assertRaises(ValidationError):
            self.Agent.create(
                {
                    "name": "Disabled with extension",
                    "vicidial_user": "DISABLED6102",
                    "odoo_user_id": self.user_one.id,
                    "webrtc_enabled": False,
                    "phone_login": "6102",
                }
            )

    def test_user_can_have_only_one_agent(self):
        self.Agent.create(
            {
                "name": "First agent",
                "vicidial_user": "FIRSTAGENT",
                "odoo_user_id": self.user_one.id,
            }
        )
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.Agent.create(
                {
                    "name": "Second agent",
                    "vicidial_user": "SECONDAGENT",
                    "odoo_user_id": self.user_one.id,
                }
            )

    def test_extension_can_belong_to_only_one_agent(self):
        self.Agent.create(
            {
                "name": "First WebRTC",
                "vicidial_user": "WEBRTC1",
                "odoo_user_id": self.user_one.id,
                "webrtc_enabled": True,
                "phone_login": "6102",
            }
        )
        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.Agent.create(
                {
                    "name": "Second WebRTC",
                    "vicidial_user": "WEBRTC2",
                    "odoo_user_id": self.user_two.id,
                    "webrtc_enabled": True,
                    "phone_login": "6102",
                }
            )

    def test_legacy_extension_input_enables_webrtc(self):
        agent = self.Agent.create(
            {
                "name": "Legacy WebRTC",
                "vicidial_user": "LEGACY6103",
                "odoo_user_id": self.user_one.id,
                "phone_login": "6103",
            }
        )
        self.assertTrue(agent.webrtc_enabled)
        self.assertEqual(agent.phone_login, "6103")
