"""Offline transport regressions; Odoo RPC/ORM checks live in addon runtime tests."""

import contextlib
import importlib.util
import io
import json
import socket
import sys
import types
import unittest
import urllib.error
import urllib.request
import urllib.response
from email.message import Message
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
CLIENT_PATH = ROOT / "custom-addons/codestra_vicidial_crm/models/middleware_client.py"


def _mark(name):
    def decorator(method):
        setattr(method, name, True)
        return method
    return decorator


def _load_client():
    # Test the real transport source without importing Odoo or mutating another
    # test's modules. This shim is not evidence that Odoo RPC enforcement passed.
    odoo = types.ModuleType("odoo")
    odoo.api = types.SimpleNamespace(
        model=_mark("_api_model"), private=_mark("_api_private")
    )
    odoo.models = types.SimpleNamespace(AbstractModel=type("AbstractModel", (), {}))
    exceptions = types.ModuleType("odoo.exceptions")
    exceptions.UserError = type("UserError", (Exception,), {})
    spec = importlib.util.spec_from_file_location("telephony_client_under_test", CLIENT_PATH)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"odoo": odoo, "odoo.exceptions": exceptions}):
        spec.loader.exec_module(module)
    return module


class Parameters:
    def __init__(self):
        self.values = {
            "codestra.middleware.telephony_originate_url":
                "https://middleware.example.test/v1/telephony/calls/originate",
            "codestra.middleware.api_key": "synthetic-call-client",
        }

    def sudo(self):
        return self

    def get_param(self, name):
        return self.values.get(name)


class TestTelephonyTransport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_client()

    def setUp(self):
        self.params = Parameters()
        self.client = self.module.TelephonyMiddlewareClient()
        self.client.env = {"ir.config_parameter": self.params}

    def send(self, payload=None, *, correlation="synthetic-correlation", key="synthetic-key"):
        return self.client.originate_call(correlation, key, {} if payload is None else payload)

    @contextlib.contextmanager
    def response(self, body=b'{"dialing":"attempting","call_id":"synthetic-call"}'):
        response = mock.MagicMock()
        response.read.return_value = body
        response.__enter__.return_value = response
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(self.module.urllib.request, "build_opener", return_value=opener):
            yield opener

    def test_dispatch_retains_private_and_model_markers(self):
        method = self.module.TelephonyMiddlewareClient.originate_call
        self.assertTrue(method._api_private)
        self.assertTrue(method._api_model)

    def test_server_request_keeps_identity_and_body(self):
        payload = {"campaign": "SYNTHETIC", "destination": "+18095550123"}
        with self.response() as opener:
            result = self.send(payload)
        request = opener.open.call_args.args[0]
        self.assertEqual(result["call_id"], "synthetic-call")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Authorization"), "Bearer synthetic-call-client")
        self.assertEqual(request.get_header("X-correlation-id"), "synthetic-correlation")
        self.assertEqual(request.get_header("Idempotency-key"), "synthetic-key")
        self.assertEqual(json.loads(request.data), dict(payload, idempotency_key="synthetic-key"))
        self.assertNotIn("idempotency_key", payload)
        opener.open.assert_called_once()

    def test_matching_embedded_identity_is_accepted(self):
        body = b'{"dialing":"blocked","correlation_id":"synthetic-correlation","idempotency_key":"synthetic-key"}'
        with self.response(body):
            self.assertEqual(self.send()["dialing"], "blocked")

    def test_missing_configuration_has_no_network_effect(self):
        for name in list(self.params.values):
            with self.subTest(name=name), self.response() as opener:
                saved = self.params.values.pop(name)
                with self.assertRaises(self.module.OriginateRejected):
                    self.send()
                self.params.values[name] = saved
                opener.open.assert_not_called()

    def test_invalid_targets_are_rejected_before_network(self):
        valid = self.params.values["codestra.middleware.telephony_originate_url"]
        for target in (
            None, 42, "", " " + valid, valid + "\n", valid + "?", valid + "#",
            valid.replace("https:", "http:"), valid.replace("https://", "https://user:pass@"),
            valid.replace("https://", "https://@"), valid.replace("/v1/", "/wrong/"),
            valid.replace(".test/", ".test:0/"), valid.replace(".test/", ".test:65536/"),
            valid.replace(".test/", ".test:bad/"), valid.replace(".test/", ".te\nst/"),
            "https://[invalid/v1/telephony/calls/originate",
        ):
            with self.subTest(target=target), self.response() as opener:
                self.params.values["codestra.middleware.telephony_originate_url"] = target
                with self.assertRaises(self.module.OriginateRejected):
                    self.send()
                opener.open.assert_not_called()

    def test_configured_https_port_remains_supported(self):
        target = "https://middleware.example.test:8443/v1/telephony/calls/originate"
        self.assertEqual(self.client._validated_target(target), target)

    def test_invalid_request_headers_have_no_network_effect(self):
        for value in (None, 1, "", "\r\nX-Injected: yes", "has space", "é", "x" * 256):
            for name in ("correlation", "key"):
                with self.subTest(name=name, value=value), self.response() as opener:
                    with self.assertRaises(self.module.OriginateRejected):
                        self.send(**{name: value})
                    opener.open.assert_not_called()

    def test_invalid_bearer_credential_has_no_network_effect(self):
        for value in (True, "has space", "\r\nX: y", "é", "x" * 8193):
            with self.subTest(value=str(value)[:20]), self.response() as opener:
                self.params.values["codestra.middleware.api_key"] = value
                with self.assertRaises(self.module.OriginateRejected):
                    self.send()
                opener.open.assert_not_called()

    def test_nonobject_payload_is_rejected(self):
        for payload in ([], [1], "body", 1, True):
            with self.subTest(payload=payload), self.response() as opener:
                with self.assertRaises(self.module.OriginateRejected):
                    self.send(payload)
                opener.open.assert_not_called()

    def test_conflicting_payload_idempotency_is_rejected(self):
        with self.response() as opener:
            with self.assertRaises(self.module.OriginateRejected):
                self.send({"idempotency_key": "other"})
            opener.open.assert_not_called()

    def test_matching_payload_idempotency_remains_supported(self):
        with self.response() as opener:
            self.send({"idempotency_key": "synthetic-key"})
            opener.open.assert_called_once()

    def test_invalid_json_request_is_rejected_before_dispatch(self):
        cycle = {}
        cycle["cycle"] = cycle
        for payload in ({"x": float("nan")}, {"x": float("inf")}, {"x": b"bytes"}, cycle):
            with self.subTest(payload_type=type(payload).__name__), self.response() as opener:
                with self.assertRaises(self.module.OriginateRejected):
                    self.send(payload)
                opener.open.assert_not_called()

    def test_oversized_request_is_rejected_before_dispatch(self):
        with self.response() as opener:
            with self.assertRaises(self.module.OriginateRejected):
                self.send({"value": "x" * 131072})
            opener.open.assert_not_called()

    def test_duplicate_response_keys_keep_outcome_unknown(self):
        bodies = (
            b'{"dialing":"attempting","dialing":"blocked"}',
            b'{"dialing":"attempting","call_id":"first","call_id":"other"}',
            b'{"dialing":"blocked","meta":{"state":1,"state":2}}',
            b'{"dialing":"attempting","\\u0064ialing":"blocked"}',
        )
        for body in bodies:
            with self.subTest(body=body), self.response(body) as opener:
                with self.assertRaises(self.module.OriginateOutcomeUnknown):
                    self.send()
                opener.open.assert_called_once()

    def test_nonfinite_response_numbers_keep_outcome_unknown(self):
        for number in (b"NaN", b"Infinity", b"-Infinity", b"1e999"):
            with self.subTest(number=number), self.response(b'{"dialing":"blocked","x":' + number + b'}'):
                with self.assertRaises(self.module.OriginateOutcomeUnknown):
                    self.send()

    def test_malformed_response_keeps_outcome_unknown(self):
        for body in (b"", b"not JSON", b"\xff", b"[]", b"null", b'"blocked"', b"x" * 131073):
            with self.subTest(size=len(body)), self.response(body) as opener:
                with self.assertRaises(self.module.OriginateOutcomeUnknown):
                    self.send()
                opener.open.assert_called_once()

    def test_excessively_nested_response_keeps_outcome_unknown(self):
        body = b"[" * 2000 + b"0" + b"]" * 2000
        with self.response(body):
            with self.assertRaises(self.module.OriginateOutcomeUnknown):
                self.send()

    def test_response_at_size_limit_is_accepted(self):
        body = b'{"dialing":"blocked"}'
        with self.response(body + b" " * (131072 - len(body))):
            self.assertEqual(self.send()["dialing"], "blocked")

    def test_response_identity_mismatch_keeps_outcome_unknown(self):
        for field in ("correlation_id", "idempotency_key"):
            for value in ("another-request", None, False):
                body = json.dumps({"dialing": "blocked", field: value}).encode()
                with self.subTest(field=field, value=value), self.response(body):
                    with self.assertRaises(self.module.OriginateOutcomeUnknown):
                        self.send()

    def test_invalid_response_shape_keeps_outcome_unknown(self):
        for result in (
            {}, {"dialing": True}, {"dialing": "unexpected"},
            {"dialing": "blocked", "reason": {}},
            *({"dialing": "attempting", "call_id": value} for value in ("", " ", "a\nb", "é", "x" * 256, 1)),
        ):
            with self.subTest(result=result), self.response(json.dumps(result).encode()):
                with self.assertRaises(self.module.OriginateOutcomeUnknown):
                    self.send()

    def test_timeouts_are_unknown_and_never_automatically_retried(self):
        for error in (TimeoutError(), socket.timeout(), urllib.error.URLError(TimeoutError())):
            with self.subTest(error=type(error).__name__), self.response() as opener:
                opener.open.side_effect = error
                result = self.send()
                self.assertEqual(result["dialing"], "unknown")
                self.assertIs(result["retry_safe"], False)
                opener.open.assert_called_once()

    def test_connection_error_remains_unknown(self):
        with self.response() as opener:
            opener.open.side_effect = urllib.error.URLError("synthetic connection failure")
            with self.assertRaises(self.module.OriginateOutcomeUnknown):
                self.send()
            opener.open.assert_called_once()

    def test_http_rejections_and_ambiguous_errors_keep_existing_classification(self):
        for status in (401, 403, 409, 422, 429, 500, 502):
            with self.subTest(status=status), self.response() as opener:
                opener.open.side_effect = urllib.error.HTTPError(
                    self.params.values["codestra.middleware.telephony_originate_url"],
                    status, "synthetic", {}, None,
                )
                expected = self.module.OriginateRejected if status in (403, 422, 429) else self.module.OriginateOutcomeUnknown
                with self.assertRaises(expected):
                    self.send()
                opener.open.assert_called_once()

    def test_redirect_chain_never_forwards_credentials(self):
        original_build = urllib.request.build_opener
        for status in (301, 302, 303, 307, 308):
            for location in ("https://other.example.test/collect", "http://other.example.test/collect", "https://middleware.example.test/other"):
                seen = []

                def respond(handler, request):
                    seen.append(request)
                    headers = Message()
                    headers["Location"] = location
                    result = urllib.response.addinfourl(io.BytesIO(b'{"dialing":"blocked"}'), headers, request.full_url, status)
                    result.msg = "Synthetic redirect"
                    return result

                class SyntheticHTTPS(urllib.request.HTTPSHandler):
                    https_open = respond

                class SyntheticHTTP(urllib.request.HTTPHandler):
                    http_open = respond

                def build(*handlers):
                    return original_build(*handlers, SyntheticHTTPS(), SyntheticHTTP())

                with self.subTest(status=status, location=location), mock.patch.object(self.module.urllib.request, "build_opener", side_effect=build):
                    with self.assertRaises(self.module.OriginateOutcomeUnknown):
                        self.send()
                self.assertEqual(len(seen), 1)
                self.assertEqual(seen[0].get_header("Authorization"), "Bearer synthetic-call-client")


if __name__ == "__main__":
    unittest.main()
