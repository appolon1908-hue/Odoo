from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests.common import TransactionCase, new_test_user


class TestTelephonyAssignment(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env["call.center.business.unit"].create(
            {"name": "WebRTC Assignment Unit", "code": "WRA"}
        )
        cls.pool = cls.env["codestra.extension.pool"].create(
            {
                "name": "WebRTC Campaign Pool",
                "code": "WRA-6100",
                "business_unit_id": cls.unit.id,
                "start_extension": 6100,
                "end_extension": 6104,
                "context": "codestra_restricted",
                "active": True,
                "one_user_one_endpoint": True,
            }
        )
        cls.supervisor = new_test_user(
            cls.env,
            login="webrtc.supervisor@example.test",
            groups="codestra_vicidial_crm.group_supervisor",
        )
        cls.campaign = cls.env["codestra.vicidial.campaign"].create(
            {
                "name": "Transportation",
                "campaign_id": "TRANSPORT",
                "mode": "production",
                "extension_pool_id": cls.pool.id,
                "supervisor_ids": [(6, 0, [cls.supervisor.id])],
            }
        )
        cls.user_one = new_test_user(
            cls.env, login="webrtc.one@example.test", groups="codestra_vicidial_crm.group_agent"
        )
        cls.user_two = new_test_user(
            cls.env, login="webrtc.two@example.test", groups="codestra_vicidial_crm.group_agent"
        )
        for user in (cls.user_one, cls.user_two, cls.supervisor):
            user.codestra_tenant_id = "COD"

    def _agent(self, user, **extra):
        values = {
            "name": user.name,
            "vicidial_user": "vici-%s" % user.id,
            "odoo_user_id": user.id,
            "tenant_id": "COD",
            "primary_campaign_id": self.campaign.id,
            "campaign_ids": [(6, 0, [self.campaign.id])],
            "supervisor_user_id": self.supervisor.id,
        }
        values.update(extra)
        return self.env["codestra.vicidial.agent"].create(values)

    def test_every_agent_auto_receives_one_extension_and_6101_is_skipped(self):
        first = self._agent(self.user_one)
        second = self._agent(self.user_two)
        self.assertEqual(first.phone_login, "6100")
        self.assertEqual(second.phone_login, "6102")
        self.assertNotEqual(first.phone_login, "6101")
        self.assertNotEqual(second.phone_login, "6101")

    def test_webrtc_is_optional_and_separate_from_extension(self):
        agent = self._agent(self.user_one)
        self.assertTrue(agent.phone_login)
        self.assertFalse(agent.webrtc_enabled)
        self.assertEqual(agent.webrtc_status, "disabled")
        self.assertEqual(agent.webrtc_device_limit, 1)

    def test_super_admin_can_enable_webrtc_without_changing_extension(self):
        agent = self._agent(self.user_one)
        extension = agent.phone_login
        agent.write({"webrtc_enabled": True})
        self.assertTrue(agent.webrtc_enabled)
        self.assertEqual(agent.phone_login, extension)
        event = self.env["codestra.integration.event"].sudo().search(
            [("event_type", "=", "telephony.webrtc.enable")], order="id desc", limit=1
        )
        self.assertTrue(event)
        self.assertNotIn("credential", event.payload_json.lower())

    def test_agent_cannot_change_assignment_fields(self):
        agent = self._agent(self.user_one)
        with self.assertRaises(AccessError):
            agent.with_user(self.user_one).write({"webrtc_enabled": True})
        with self.assertRaises(AccessError):
            agent.with_user(self.user_one).write({"supervisor_user_id": False})
        with self.assertRaises(AccessError):
            agent.with_user(self.user_one).write({"primary_campaign_id": self.campaign.id})

    def test_supervisor_can_view_but_not_assign_webrtc(self):
        agent = self._agent(self.user_one)
        visible = self.env["codestra.vicidial.agent"].with_user(self.supervisor).search(
            [("id", "=", agent.id)]
        )
        self.assertEqual(visible, agent)
        with self.assertRaises(AccessError):
            agent.with_user(self.supervisor).write({"webrtc_enabled": True})

    def test_one_odoo_user_has_only_one_agent(self):
        self._agent(self.user_one)
        with self.assertRaises(ValidationError):
            self._agent(self.user_one, vicidial_user="second-user-agent", phone_login="6104")

    def test_second_webrtc_endpoint_is_rejected(self):
        agent = self._agent(self.user_one, webrtc_enabled=True)
        phone = self.env["codestra.vicidial.phone"].create(
            {
                "name": "Browser endpoint",
                "extension": agent.phone_login,
                "assigned_agent_id": agent.id,
                "protocol": "PJSIP",
                "active": True,
            }
        )
        self.assertEqual(agent.webrtc_device_count, 1)
        self.assertTrue(phone)
        with self.assertRaises(ValidationError):
            self.env["codestra.vicidial.phone"].create(
                {
                    "name": "Second browser endpoint",
                    "extension": agent.phone_login,
                    "assigned_agent_id": agent.id,
                    "protocol": "PJSIP",
                    "active": True,
                }
            )

    def test_webrtc_off_releases_projection_and_queues_revoke(self):
        agent = self._agent(self.user_one, webrtc_enabled=True)
        phone = self.env["codestra.vicidial.phone"].create(
            {
                "name": "Browser endpoint",
                "extension": agent.phone_login,
                "assigned_agent_id": agent.id,
                "active": True,
            }
        )
        agent.write({"webrtc_enabled": False})
        self.assertFalse(phone.active)
        self.assertEqual(phone.status, "REVOCATION_PENDING")
        self.assertTrue(
            self.env["codestra.integration.event"].sudo().search_count(
                [("event_type", "=", "telephony.webrtc.disable")]
            )
        )

    def test_replace_extension_releases_old_then_requests_new(self):
        agent = self._agent(self.user_one, webrtc_enabled=True)
        old_extension = agent.phone_login
        phone = self.env["codestra.vicidial.phone"].create(
            {
                "name": "Old browser endpoint",
                "extension": old_extension,
                "assigned_agent_id": agent.id,
                "active": True,
            }
        )
        agent.action_replace_extension()
        self.assertFalse(phone.active)
        self.assertNotEqual(agent.phone_login, old_extension)
        event = self.env["codestra.integration.event"].sudo().search(
            [("event_type", "=", "telephony.extension.replace")], order="id desc", limit=1
        )
        self.assertTrue(event)
        self.assertIn("revoke_old_endpoint", event.payload_json)
        self.assertIn("provision_new_assignment", event.payload_json)

    def test_campaign_without_active_pool_fails_closed(self):
        campaign = self.env["codestra.vicidial.campaign"].create(
            {"name": "No Pool", "campaign_id": "NOPOOL", "mode": "test"}
        )
        with self.assertRaises(UserError):
            self.env["codestra.vicidial.agent"].create(
                {
                    "name": "No Pool Agent",
                    "vicidial_user": "no-pool",
                    "odoo_user_id": self.user_one.id,
                    "primary_campaign_id": campaign.id,
                    "campaign_ids": [(6, 0, [campaign.id])],
                }
            )
