from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, new_test_user


class TestWebRTCPhoneAssignment(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = new_test_user(
            cls.env,
            login="webrtc_agent_test",
            groups="codestra_vicidial_crm.group_agent",
            context={"no_reset_password": True},
        )
        cls.agent = cls.env["codestra.vicidial.agent"].create(
            {
                "name": "WebRTC Agent",
                "vicidial_user": "WEBRTC001",
                "tenant_id": "COD",
                "phone_login": "6101",
                "odoo_user_id": cls.user.id,
                "webrtc_enabled": True,
            }
        )
        cls.Phone = cls.env["codestra.vicidial.phone"]

    def test_user_option_and_single_phone(self):
        self.assertTrue(self.user.webrtc_enabled)
        phone = self.Phone.create(
            {
                "name": "WebRTC 6101",
                "extension": "6101",
                "login": "6101",
                "assigned_agent_id": self.agent.id,
                "is_webrtc": True,
                "active": True,
            }
        )
        self.assertEqual(phone.assigned_agent_id, self.agent)
        self.assertEqual(self.agent.phone_ids, phone)

        with self.assertRaises((IntegrityError, ValidationError)):
            self.Phone.create(
                {
                    "name": "Second extension",
                    "extension": "6102",
                    "login": "6102",
                    "assigned_agent_id": self.agent.id,
                    "is_webrtc": True,
                    "active": True,
                }
            )
        self.env.cr.rollback()

    def test_webrtc_must_match_agent_option(self):
        with self.assertRaises(ValidationError):
            self.Phone.create(
                {
                    "name": "Unapproved WebRTC",
                    "extension": "6103",
                    "login": "6103",
                    "assigned_agent_id": self.agent.id,
                    "is_webrtc": False,
                    "active": True,
                }
            )

    def test_disabling_web_rtc_requires_unassignment(self):
        phone = self.Phone.create(
            {
                "name": "WebRTC 6101",
                "extension": "6101",
                "login": "6101",
                "assigned_agent_id": self.agent.id,
                "is_webrtc": True,
                "active": True,
            }
        )
        self.assertTrue(phone.is_webrtc)
        with self.assertRaises(ValidationError):
            self.agent.write({"webrtc_enabled": False})
