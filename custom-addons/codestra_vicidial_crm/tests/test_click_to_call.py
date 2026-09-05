import uuid

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
        self.env.user.write(
            {
                "codestra_tenant_id": "COD",
                "keycloak_subject": str(uuid.uuid4()),
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
        self.env["codestra.vicidial.call"].search(
            [("crm_lead_id", "=", self.lead.id)], limit=1
        )._dispatch_click_to_call()
        self.assertEqual(action["params"]["type"], "success")
        self.assertEqual(captured["campaign"], self.lead.x_vicidial_campaign_id)
        self.assertEqual(captured["destination_country"], "DO")
        self.assertEqual(captured["caller_id"], "+18095550999")
        self.assertNotEqual(captured["caller_id"], self.agent.phone_login)

    def test_agent_acl_path_persists_lifecycle_bindings(self):
        user = self.env["res.users"].create(
            {
                "name": "Synthetic click-to-call agent",
                "login": "click-agent-" + self._testMethodName,
                "codestra_tenant_id": "COD",
                "keycloak_subject": str(uuid.uuid4()),
                "call_center_business_unit_ids": [
                    (6, 0, self.lead.business_unit_id.ids)
                ],
                "group_ids": [
                    (4, self.env.ref("codestra_vicidial_crm.group_agent").id),
                    (4, self.env.ref("sales_team.group_sale_salesman").id),
                    (4, self.env.ref("call_center_core.group_call_center_user").id),
                ],
            }
        )
        self.agent.odoo_user_id = user
        self.lead.user_id = user

        def fake_originate(_self, correlation_id, idempotency_key, payload):
            return {
                "dialing": "attempting",
                "reason": "accepted",
                "call_id": "acl-bound-call-id",
            }

        self.patch(
            type(self.env["codestra.telephony.middleware.client"]),
            "originate_call",
            fake_originate,
        )
        action = self.lead.with_user(user).action_click_to_call()
        self.env["codestra.vicidial.call"].search(
            [("crm_lead_id", "=", self.lead.id)], limit=1
        )._dispatch_click_to_call()
        self.assertEqual(action["params"]["type"], "success")
        call = self.env["codestra.vicidial.call"].search(
            [("call_id", "=", "acl-bound-call-id")]
        )
        self.assertEqual(call.agent_id, self.agent)
        self.assertEqual(call.tenant_id, "COD")
        self.assertEqual(call.keycloak_subject, user.keycloak_subject)

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
        call = self.env["codestra.vicidial.call"].search(
            [("crm_lead_id", "=", self.lead.id)], limit=1
        )
        call._dispatch_click_to_call()
        self.env["ir.config_parameter"].sudo().set_param(
            "codestra.telephony.approved_outbound_caller_id", "+18095550888"
        )
        second = self.lead.action_click_to_call()
        call._dispatch_click_to_call()
        self.assertEqual(first["params"]["type"], "success")
        self.assertEqual(second["params"]["type"], "success")
        self.assertEqual(requests[0][0:2], requests[1][0:2])
        self.assertEqual(requests[0][2], requests[1][2])
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
        call = self.env["codestra.vicidial.call"].search(
            [("crm_lead_id", "=", self.lead.id)], limit=1
        )
        call._dispatch_click_to_call()
        self.assertEqual(action["params"]["type"], "success")
        self.assertEqual(call.state, "failed")
        self.assertEqual(call.status, "blocked")

    def test_active_call_blocks_other_lead_for_same_agent(self):
        other = self.lead.copy({"name": "Other lead", "phone": "+18095550124"})
        self.env["codestra.vicidial.call"].create(
            {
                "name": "Existing active call",
                "crm_lead_id": other.id,
                "agent_id": self.agent.id,
                "campaign_id": self.agent.campaign_ids.id,
                "tenant_id": self.agent.tenant_id,
                "destination": other.phone,
                "state": "held",
                "status": "held",
                "idempotency_key": str(uuid.uuid4()),
            }
        )
        with self.assertRaises(UserError):
            self.lead.action_click_to_call()

    def test_committed_requesting_placeholder_is_reclaimed_with_same_key(self):
        first = self.lead.action_click_to_call()
        call = self.env["codestra.vicidial.call"].search(
            [("crm_lead_id", "=", self.lead.id)], limit=1
        )
        second = self.lead.action_click_to_call()
        self.assertEqual(first["params"]["type"], "success")
        self.assertEqual(second["params"]["type"], "success")
        self.assertEqual(call.status, "requesting")
