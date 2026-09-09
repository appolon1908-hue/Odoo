"""Offline regressions for the canonical telephony command envelope.

These exercise the real transport source without importing Odoo. They are not
evidence that Odoo RPC enforcement or a live Middleware dispatch passed.
"""

import contextlib
import importlib.util
import json
import socket
import sys
import types
import unittest
import urllib.error
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
CLIENT_PATH = ROOT / "custom-addons/codestra_vicidial_crm/models/middleware_client.py"

OPERATION_ID = "6f1d2c34-5a6b-4c7d-8e9f-0a1b2c3d4e5f"
CORRELATION_ID = "11112222-3333-4444-5555-666677778888"
COMMAND_URL = "https://middleware.example.test/v1/telephony/commands"


def _mark(name):
    def decorator(method):
        setattr(method, name, True)
        return method

    return decorator


def _load_client():
    odoo = types.ModuleType("odoo")
    odoo.api = types.SimpleNamespace(
        model=_mark("_api_model"), private=_mark("_api_private")
    )
    odoo.models = types.SimpleNamespace(AbstractModel=type("AbstractModel", (), {}))
    exceptions = types.ModuleType("odoo.exceptions")
    exceptions.UserError = type("UserError", (Exception,), {})
    spec = importlib.util.spec_from_file_location(
        "telephony_command_under_test", CLIENT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"odoo": odoo, "odoo.exceptions": exceptions}):
        spec.loader.exec_module(module)
    return module


class Parameters:
    def __init__(self, command_url=COMMAND_URL):
        self.values = {
            "codestra.middleware.telephony_command_url": command_url,
            "codestra.middleware.api_key": "synthetic-command-client",
        }

    def sudo(self):
        return self

    def get_param(self, name):
        return self.values.get(name)


def _values(**overrides):
    values = {
        "tenant_id": "codestra",
        "business_unit_id": "BU-DO-1",
        "campaign_id": "SYNTHETIC_CAMPAIGN",
        "agent_id": "agent-0001",
        "odoo_user_id": "42",
        "odoo_lead_id": "9001",
        "operation_id": OPERATION_ID,
        "correlation_id": CORRELATION_ID,
        "requested_at": "2026-09-08T12:00:00Z",
    }
    values.update(overrides)
    return {k: v for k, v in values.items() if v is not None}


def _operation(**overrides):
    body = {
        "operation_id": OPERATION_ID,
        "state": "PERSISTED",
        "external_effect": False,
        "calls_placed": 0,
    }
    body.update(overrides)
    return json.dumps(body).encode("utf-8")


class TelephonyCommandEnvelopeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_client()

    def setUp(self):
        self.params = Parameters()
        self.client = self.module.TelephonyMiddlewareClient()
        self.client.env = {"ir.config_parameter": self.params}

    @contextlib.contextmanager
    def response(self, body=None):
        response = mock.MagicMock()
        response.read.return_value = _operation() if body is None else body
        response.__enter__.return_value = response
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(
            self.module.urllib.request, "build_opener", return_value=opener
        ):
            yield opener

    def send(self, values=None):
        return self.client.originate_command(
            CORRELATION_ID, "synthetic-key", _values() if values is None else values
        )

    # --- envelope shape -------------------------------------------------

    def test_dispatch_retains_private_and_model_markers(self):
        method = self.module.TelephonyMiddlewareClient.originate_command
        self.assertTrue(method._api_private)
        self.assertTrue(method._api_model)

    def test_request_body_is_the_canonical_command(self):
        with self.response() as opener:
            self.send()
        body = json.loads(opener.open.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(body["type"], "telephony.call.originate.v1")
        self.assertEqual(body["schema_version"], 1)
        self.assertEqual(body["operation_id"], OPERATION_ID)
        self.assertEqual(body["correlation_id"], CORRELATION_ID)
        self.assertEqual(body["requested_at"], "2026-09-08T12:00:00Z")

    def test_request_carries_correlation_and_idempotency_headers(self):
        with self.response() as opener:
            self.send()
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_header("X-correlation-id"), CORRELATION_ID)
        self.assertEqual(request.get_header("Idempotency-key"), "synthetic-key")
        self.assertEqual(request.get_method(), "POST")

    def test_command_carries_no_field_outside_the_closed_schema(self):
        allowed = {
            "type",
            "schema_version",
            "tenant_id",
            "business_unit_id",
            "campaign_id",
            "agent_id",
            "odoo_user_id",
            "odoo_lead_id",
            "vicidial_user_id",
            "vicidial_campaign_id",
            "vicidial_lead_id",
            "operation_id",
            "correlation_id",
            "requested_at",
        }
        with self.response() as opener:
            self.send()
        body = json.loads(opener.open.call_args.args[0].data.decode("utf-8"))
        self.assertLessEqual(set(body), allowed)

    def test_legacy_only_fields_are_rejected_not_silently_dropped(self):
        # destination/caller_id have no canonical field. Dropping them quietly
        # would let a caller believe Odoo still chooses the dialled number.
        for field in ("destination", "caller_id", "recording_requested"):
            with self.subTest(field=field):
                with self.assertRaises(self.module.OriginateRejected):
                    self.send(_values(**{field: "x"}))

    # --- identity validation --------------------------------------------

    def test_subject_tokens_reject_separators(self):
        for bad in ("has.dot", "has/slash", "has space", "*", "", "-leading"):
            with self.subTest(value=bad):
                with self.assertRaises(self.module.OriginateRejected):
                    self.send(_values(campaign_id=bad))

    def test_operation_and_correlation_must_be_uuids(self):
        with self.assertRaises(self.module.OriginateRejected):
            self.send(_values(operation_id="not-a-uuid"))
        with self.assertRaises(self.module.OriginateRejected):
            self.send(_values(correlation_id="not-a-uuid"))

    def test_correlation_header_must_match_the_command(self):
        other = "99998888-7777-6666-5555-444433332222"
        with self.assertRaises(self.module.OriginateRejected):
            self.client.originate_command(
                CORRELATION_ID, "synthetic-key", _values(correlation_id=other)
            )

    def test_timestamp_must_be_rfc3339(self):
        for bad in ("2026-09-08", "08/09/2026", "2026-09-08 12:00:00"):
            with self.subTest(value=bad):
                with self.assertRaises(self.module.OriginateRejected):
                    self.send(_values(requested_at=bad))

    def test_missing_required_identity_is_rejected(self):
        with self.assertRaises(self.module.OriginateRejected):
            self.send(_values(agent_id=None))

    def test_target_must_be_the_canonical_command_path(self):
        self.params.values["codestra.middleware.telephony_command_url"] = (
            "https://middleware.example.test/v1/telephony/calls/originate"
        )
        with self.assertRaises(self.module.OriginateRejected):
            self.send()

    def test_target_must_be_credential_free_https(self):
        for bad in (
            "http://middleware.example.test/v1/telephony/commands",
            "https://user:pass@middleware.example.test/v1/telephony/commands",
            "https://middleware.example.test/v1/telephony/commands?x=1",
        ):
            with self.subTest(target=bad):
                self.params.values["codestra.middleware.telephony_command_url"] = bad
                with self.assertRaises(self.module.OriginateRejected):
                    self.send()

    # --- operation outcome mapping ---------------------------------------

    def test_accepted_states_report_attempting(self):
        for state in ("PERSISTED", "DISPATCH_PENDING", "DISPATCHED", "COMPLETED"):
            with self.subTest(state=state):
                with self.response(_operation(state=state)):
                    self.assertEqual(self.send()["dialing"], "attempting")

    def test_indeterminate_states_report_unknown(self):
        for state in ("INDETERMINATE", "RECONCILING"):
            with self.subTest(state=state):
                with self.response(_operation(state=state)):
                    self.assertEqual(self.send()["dialing"], "unknown")

    def test_policy_denied_without_effect_is_blocked(self):
        with self.response(_operation(state="POLICY_DENIED")):
            result = self.send()
        self.assertEqual(result["dialing"], "blocked")
        self.assertFalse(result["external_effect"])

    def test_terminal_state_with_external_effect_is_unknown_not_blocked(self):
        # A wrong "rejected" invites a retry that double-dials.
        for state in ("FAILED", "CANCELLED"):
            with self.subTest(state=state):
                with self.response(_operation(state=state, external_effect=True)):
                    self.assertEqual(self.send()["dialing"], "unknown")

    def test_terminal_state_with_calls_placed_is_unknown_not_blocked(self):
        with self.response(_operation(state="FAILED", calls_placed=1)):
            self.assertEqual(self.send()["dialing"], "unknown")

    def test_policy_denied_claiming_effect_is_not_trusted_as_blocked(self):
        with self.response(_operation(state="POLICY_DENIED", external_effect=True)):
            self.assertEqual(self.send()["dialing"], "unknown")

    # --- response hardening ----------------------------------------------

    def test_non_string_states_report_unknown_outcome(self):
        for state in ([], {}, None, True, 7):
            with self.subTest(state=state), self.response(_operation(state=state)):
                with self.assertRaises(self.module.OriginateOutcomeUnknown):
                    self.send()

    def test_impossible_timestamp_is_rejected_before_transport(self):
        for timestamp in ("2026-02-30T12:00:00Z", "2026-09-08T25:00:00Z"):
            values = _values()
            values["requested_at"] = timestamp
            with self.subTest(timestamp=timestamp), self.response() as opener:
                with self.assertRaises(self.module.OriginateRejected):
                    self.send(values)
                opener.open.assert_not_called()

    def test_unknown_state_is_an_unknown_outcome(self):
        with self.response(_operation(state="SOMETHING_NEW")):
            with self.assertRaises(self.module.OriginateOutcomeUnknown):
                self.send()

    def test_operation_id_mismatch_is_an_unknown_outcome(self):
        other = "00000000-0000-4000-8000-000000000000"
        with self.response(_operation(operation_id=other)):
            with self.assertRaises(self.module.OriginateOutcomeUnknown):
                self.send()

    def test_extra_response_field_is_an_unknown_outcome(self):
        body = json.loads(_operation())
        body["surprise"] = True
        with self.response(json.dumps(body).encode("utf-8")):
            with self.assertRaises(self.module.OriginateOutcomeUnknown):
                self.send()

    def test_boolean_calls_placed_is_rejected(self):
        with self.response(_operation(calls_placed=True)):
            with self.assertRaises(self.module.OriginateOutcomeUnknown):
                self.send()

    def test_negative_calls_placed_is_rejected(self):
        with self.response(_operation(calls_placed=-1)):
            with self.assertRaises(self.module.OriginateOutcomeUnknown):
                self.send()

    def test_duplicate_response_members_are_rejected(self):
        body = b'{"operation_id":"%s","state":"PERSISTED","state":"POLICY_DENIED",' % (
            OPERATION_ID.encode()
        ) + b'"external_effect":false,"calls_placed":0}'
        with self.response(body):
            with self.assertRaises(self.module.OriginateOutcomeUnknown):
                self.send()

    def test_non_finite_response_number_is_rejected(self):
        body = (
            b'{"operation_id":"' + OPERATION_ID.encode() + b'","state":"PERSISTED",'
            b'"external_effect":false,"calls_placed":NaN}'
        )
        with self.response(body):
            with self.assertRaises(self.module.OriginateOutcomeUnknown):
                self.send()

    def test_oversized_response_is_rejected(self):
        with self.response(b"{" + b"x" * (self.module._MAX_MESSAGE_BYTES + 8)):
            with self.assertRaises(self.module.OriginateOutcomeUnknown):
                self.send()

    def test_timeout_reports_unknown_and_is_not_retry_safe(self):
        opener = mock.Mock()
        opener.open.side_effect = socket.timeout()
        with mock.patch.object(
            self.module.urllib.request, "build_opener", return_value=opener
        ):
            result = self.send()
        self.assertEqual(result["dialing"], "unknown")
        self.assertFalse(result["retry_safe"])
        self.assertEqual(result["operation_id"], OPERATION_ID)

    def test_server_error_is_an_unknown_outcome(self):
        opener = mock.Mock()
        opener.open.side_effect = urllib.error.HTTPError(
            COMMAND_URL, 500, "boom", None, None
        )
        with mock.patch.object(
            self.module.urllib.request, "build_opener", return_value=opener
        ):
            with self.assertRaises(self.module.OriginateOutcomeUnknown):
                self.send()

    def test_authorization_failure_is_rejected_not_unknown(self):
        opener = mock.Mock()
        opener.open.side_effect = urllib.error.HTTPError(
            COMMAND_URL, 403, "denied", None, None
        )
        with mock.patch.object(
            self.module.urllib.request, "build_opener", return_value=opener
        ):
            with self.assertRaises(self.module.OriginateRejected):
                self.send()

    def test_redirects_are_refused(self):
        handler = self.module._NoTelephonyRedirect()
        self.assertIsNone(
            handler.redirect_request(None, None, 302, "Found", {}, COMMAND_URL)
        )

    def test_unconfigured_command_url_is_rejected(self):
        self.params.values.pop("codestra.middleware.telephony_command_url")
        with self.assertRaises(self.module.OriginateRejected):
            self.send()

    def test_legacy_originate_path_is_unchanged(self):
        # The live click-to-call default must not move as a side effect: the
        # legacy validator still accepts only the legacy route, and the canonical
        # validator still accepts only the canonical one.
        legacy_url = "https://middleware.example.test/v1/telephony/calls/originate"
        self.assertEqual(self.client._validated_target(legacy_url), legacy_url)
        with self.assertRaises(self.module.OriginateRejected):
            self.client._validated_target(COMMAND_URL)
        self.assertEqual(self.client._validated_command_target(COMMAND_URL), COMMAND_URL)
        with self.assertRaises(self.module.OriginateRejected):
            self.client._validated_command_target(legacy_url)


if __name__ == "__main__":
    unittest.main()
