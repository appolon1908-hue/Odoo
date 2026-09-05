from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase


class TestClickToCall(TransactionCase):
    def setUp(self):
        super().setUp()
        unit = self.env.ref("call_center_core.business_unit_digital")
        suffix = self._testMethodName
        campaign = self.env["codestra.vicidial.campaign"].create(
            {
                "name": "Synthetic",
                "campaign_id": "TEST_SYN_" + suffix,
                "mode": "test",
            }
        )
        self.agent = self.env["codestra.vicidial.agent"].create(
            {
                "name": "Test Agent",
                "vicidial_user": "agent.syn." + suffix,
                "employee_code": "EMP-" + suffix,
                "odoo_user_id": self.env.uid,
                "phone_login": "61" + str(abs(hash(suffix)) % 10000),
                "status": "ready",
                "campaign_ids": [(6, 0, [campaign.id])],
            }
        )
        self.lead = self.env["crm.lead"].create(
            {
                "name": "Click-to-call test",
                "business_unit_id": unit.id,
                "x_vicidial_campaign_id": campaign.campaign_id,
                "phone": "+18095550123",
            }
        )
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("codestra.telephony.destination_class", "CONSENTED_PILOT")
        params.set_param("codestra.telephony.destination_country", "DO")
        params.set_param(
            "codestra.telephony.approved_outbound_caller_id", "+18095550999"
        )

    def test_fail_closed_guards(self):
        self.agent.status = "paused"
        with self.assertRaises(UserError):
            self.lead.action_click_to_call()

    def test_middleware_target_requires_credential_free_https(self):
        client = self.env["codestra.telephony.middleware.client"]
        valid = "https://middleware.example.test/v1/telephony/calls/originate"
        self.assertEqual(client._validated_target(valid), valid)
        for unsafe in (
            "http://middleware.example.test/api/v1/telephony/originate",
            "https://user:secret@middleware.example.test/api/v1/telephony/originate",
            "https://middleware.example.test/api/v1/telephony/originate?redirect=1",
            "https://middleware.example.test/api/v1/telephony/originate",
        ):
            with self.subTest(unsafe=unsafe), self.assertRaises(UserError):
                client._validated_target(unsafe)
        self.agent.status = "ready"
        self.lead.x_do_not_call = True
        with self.assertRaises(UserError):
            self.lead.action_click_to_call()

    def test_calls_only_middleware(self):
        captured = {}

        def fake_originate(_self, correlation_id, idempotency_key, payload):
            captured.update(payload)
            return {"dialing": "attempting", "reason": "accepted"}

        self.patch(
            type(self.env["codestra.telephony.middleware.client"]),
            "originate_call",
            fake_originate,
        )
        action = self.lead.action_click_to_call()
        self.assertEqual(action["params"]["type"], "success")
        self.assertEqual(captured["campaign"], self.lead.x_vicidial_campaign_id)
        self.assertEqual(captured["destination_country"], "DO")
        self.assertEqual(captured["caller_id"], "+18095550999")
        self.assertNotEqual(captured["caller_id"], self.agent.phone_login)

    def test_unknown_timeout_reuses_request_instead_of_creating_duplicate(self):
        requests = []

        def fake_originate(_self, correlation_id, idempotency_key, payload):
            requests.append((correlation_id, idempotency_key, payload))
            if len(requests) == 1:
                return {"dialing": "unknown", "reason": "timeout", "retry_safe": False}
            return {
                "dialing": "attempting",
                "reason": "accepted",
                "call_id": "synthetic-call-id",
            }

        self.patch(
            type(self.env["codestra.telephony.middleware.client"]),
            "originate_call",
            fake_originate,
        )
        first = self.lead.action_click_to_call()
        second = self.lead.action_click_to_call()
        self.assertEqual(first["params"]["type"], "warning")
        self.assertEqual(second["params"]["type"], "success")
        self.assertEqual(requests[0][0:2], requests[1][0:2])
        calls = self.env["codestra.vicidial.call"].search(
            [("crm_lead_id", "=", self.lead.id)]
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls.call_id, "synthetic-call-id")

    def test_policy_denial_is_visible(self):
        def fake_originate(_self, correlation_id, idempotency_key, payload):
            return {"dialing": "blocked", "reason": "policy_decision:DENY"}

        self.patch(
            type(self.env["codestra.telephony.middleware.client"]),
            "originate_call",
            fake_originate,
        )
        action = self.lead.action_click_to_call()
        self.assertEqual(action["params"]["type"], "info")
        self.assertTrue(action["params"]["sticky"])
