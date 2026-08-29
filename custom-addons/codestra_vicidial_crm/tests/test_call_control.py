import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase

from ..controllers import call_control as call_control_controller


class TestCallControl(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group = cls.env.ref("codestra_vicidial_crm.group_agent")
        cls.agent_user = cls.env["res.users"].create(
            {
                "name": "Synthetic Agent 6101",
                "login": "synthetic-agent-6101@example.test",
                "keycloak_subject": str(uuid.UUID(int=6101)),
                "codestra_tenant_id": "COD",
                "group_ids": [(6, 0, [group.id])],
            }
        )
        cls.other_user = cls.env["res.users"].create(
            {
                "name": "Other Agent",
                "login": "synthetic-agent-6102@example.test",
                "keycloak_subject": str(uuid.UUID(int=6102)),
                "codestra_tenant_id": "COD",
                "group_ids": [(6, 0, [group.id])],
            }
        )
        cls.campaign = cls.env["codestra.vicidial.campaign"].search(
            [("campaign_id", "=", "TEST_SYN")], limit=1
        ) or cls.env["codestra.vicidial.campaign"].create(
            {
                "name": "Synthetic Test",
                "campaign_id": "TEST_SYN",
                "mode": "test",
            }
        )
        cls.agent = cls.env["codestra.vicidial.agent"].create(
            {
                "name": "Synthetic Agent 6101",
                "vicidial_user": "SYN6101",
                "tenant_id": "COD",
                "phone_login": "6101",
                "odoo_user_id": cls.agent_user.id,
                "campaign_ids": [(6, 0, [cls.campaign.id])],
            }
        )

    def call(self, suffix="one"):
        return self.env["codestra.vicidial.call"].create(
            {
                "name": "Synthetic call " + suffix,
                "call_id": "call-" + suffix,
                "correlation_id": "corr-" + suffix,
                "asterisk_uniqueid": "uid-" + suffix,
                "uniqueid": "uid-" + suffix,
                "linkedid": "linked-" + suffix,
                "tenant_id": "COD",
                "business_unit_id": "COD",
                "keycloak_subject": self.agent_user.keycloak_subject,
                "campaign_id": self.campaign.id,
                "campaign_code": "TEST_SYN",
                "agent_id": self.agent.id,
                "vicidial_user": "SYN6101",
                "extension": "6101",
                "direction": "inbound",
                "state": "new",
                "sequence": 0,
                "idempotency_key": "call-key-" + suffix,
            }
        )

    def event(self, suffix, state, sequence):
        return {
            "event_id": f"event-{suffix}-{sequence}",
            "event_type": "call." + state,
            "timestamp": fields.Datetime.now(),
            "state": state,
            "sequence": sequence,
        }

    def test_number_normalization_and_exact_matching(self):
        partner = self.env["res.partner"].create({"name": "Synthetic Customer", "phone": "+1 (617) 555-0100"})
        result = self.env["codestra.vicidial.call"].match_customer("617-555-0100", "TEST_SYN")
        self.assertEqual(result["normalized_number"], "+16175550100")
        self.assertEqual(result["match"], "exact")
        self.assertEqual(result["matches"][0]["id"], partner.id)
        with self.assertRaises(ValidationError):
            self.env["codestra.vicidial.call"].normalize_number("555-CALL-NOW")
        self.assertEqual(self.env["codestra.vicidial.call"].normalize_number("(809) 555-0100"), "+18095550100")
        self.assertEqual(self.env["codestra.vicidial.call"].normalize_number("829-555-0100"), "+18295550100")
        self.assertEqual(self.env["codestra.vicidial.call"].normalize_number("849 555 0100"), "+18495550100")
        self.assertEqual(self.env["codestra.vicidial.call"].normalize_number("00442079460123"), "+442079460123")
        with self.assertRaises(ValidationError):
            self.env["codestra.vicidial.call"].normalize_number("12+34567890")

    def test_multiple_matches_are_ambiguous(self):
        self.env["res.partner"].create({"name": "First", "phone": "+1 809 555 0199"})
        self.env["res.partner"].create({"name": "Second", "phone": "809-555-0199"})
        result = self.env["codestra.vicidial.call"].match_customer("+18095550199", "TEST_SYN")
        self.assertEqual(result["match"], "ambiguous")
        self.assertEqual(len(result["matches"]), 2)

    def test_monotonic_transition_duplicate_and_out_of_order(self):
        call = self.call("ordering")
        self.assertTrue(call.apply_authoritative_event(self.event("ordering-ring", "ringing", 1))["applied"])
        connected = self.event("ordering-connected", "connected", 2)
        self.assertTrue(call.apply_authoritative_event(connected)["applied"])
        self.assertTrue(call.apply_authoritative_event(connected)["duplicate"])
        conflict = dict(connected, sequence=99)
        with self.assertRaises(ValidationError):
            call.apply_authoritative_event(conflict)
        self.assertTrue(call.apply_authoritative_event(self.event("ordering-end", "completed", 3))["applied"])
        stale = call.apply_authoritative_event(self.event("ordering-stale", "ringing", 4))
        self.assertFalse(stale["applied"])
        self.assertEqual(call.state, "completed")

    def test_impossible_transition_is_recorded_without_regression(self):
        call = self.call("impossible")
        result = call.apply_authoritative_event(self.event("impossible", "held", 1))
        self.assertFalse(result["applied"])
        self.assertEqual(call.state, "new")
        self.assertEqual(
            self.env["codestra.vicidial.call.event"].search_count([("idempotency_key", "=", "event-impossible-1")]), 1
        )

    def test_recording_metadata_can_arrive_after_call_end(self):
        call = self.call("recording")
        call.apply_authoritative_event(self.event("recording-ring", "ringing", 1))
        call.apply_authoritative_event(self.event("recording-connect", "connected", 2))
        call.apply_authoritative_event(self.event("recording-end", "completed", 3))
        event = self.event("recording-ready", "completed", 4)
        event.update(
            {
                "event_type": "call.recording_available",
                "state": None,
                "recording_id": "recording-synthetic-1",
                "recording_reference": "restricted/reference.wav",
                "duration": 10,
            }
        )
        self.assertTrue(call.apply_authoritative_event(event)["applied"])
        self.assertEqual(call.recording_status, "available")
        self.assertEqual(call.recording_ids.recording_id, "recording-synthetic-1")

    def test_cross_agent_call_access_denied(self):
        call = self.call("isolation")
        with self.assertRaises(AccessError):
            call.with_user(self.other_user)._check_call_owner()

    def test_callback_replay_returns_the_original_callback(self):
        call = self.call("callback-replay")
        call.normalized_number = "+18095550100"
        lead = self.env["crm.lead"].create({"name": "Synthetic Callback Lead"})
        call.crm_lead_id = lead
        controller = call_control_controller.CallControlAPI()
        first_at = fields.Datetime.now() + timedelta(hours=1)
        second_at = first_at + timedelta(hours=1)
        request = SimpleNamespace(env=self.env)
        with (
            patch.object(call_control_controller, "request", request),
            patch.object(controller, "_owned_call", return_value=call),
        ):
            first = controller.callback(
                call.call_id,
                fields.Datetime.to_string(first_at),
                "UTC",
                "First synthetic callback",
                "callback-replay-key-0001",
            )
            second = controller.callback(
                call.call_id,
                fields.Datetime.to_string(second_at),
                "UTC",
                "Second synthetic callback",
                "callback-replay-key-0002",
            )
            replay = controller.callback(
                call.call_id,
                fields.Datetime.to_string(first_at),
                "UTC",
                "First synthetic callback",
                "callback-replay-key-0001",
            )
        self.assertNotEqual(first["callback_id"], second["callback_id"])
        self.assertTrue(replay["duplicate"])
        self.assertEqual(replay["callback_id"], first["callback_id"])
