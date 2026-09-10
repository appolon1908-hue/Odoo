import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "custom-addons/codestra_sms_middleware/transport.py"
spec = importlib.util.spec_from_file_location("sms_middleware_transport", PATH)
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)


class TestSmsMiddlewareTransport(unittest.TestCase):
    def config(self, **changes):
        values = {"API_BASE_URL": "https://middleware.example.test", "TOKEN_URL": "https://auth.example.test/token",
                  "CLIENT_SECRET_FILE": "/run/secrets/fixture", "CA_FILE": "/run/secrets/ca",
                  "TENANT_ID": "tenant-fixture", "COMPANY_ID": "1", "BUSINESS_UNIT_ID": "2",
                  "SENDER": "Fixture", "BILLING_ACCOUNT_ID": "billing-fixture"}
        values.update(changes)
        return transport.configuration({"CODESTRA_SMS_" + key: value for key, value in values.items()})

    def test_transport_requires_safe_https_and_bounded_scope(self):
        self.assertEqual(self.config()["company_id"], 1)
        for field, value in (("API_BASE_URL", "http://middleware.example.test"),
                             ("API_BASE_URL", "https://user:secret@example.test"),
                             ("API_BASE_URL", "https://example.test/unexpected"),
                             ("API_BASE_URL", "https://example.test?redirect=1"),
                             ("TOKEN_URL", "http://keycloak:8080/token"),
                             ("CA_FILE", "relative.pem"), ("COMPANY_ID", "0"),
                             ("TENANT_ID", "tenant\nheader")):
            with self.subTest(field=field, value=value), self.assertRaises(transport.SmsTransportError):
                self.config(**{field: value})

    def test_tls_proxies_redirects_and_request_contract(self):
        config = self.config()
        with patch.object(transport.ssl, "create_default_context") as tls, patch.object(transport.urllib.request, "build_opener") as opener:
            client = transport.MiddlewareSmsClient(config)
            tls.assert_called_once_with(cafile=config["ca_file"])
            handlers = opener.call_args.args
            self.assertEqual(handlers[0].proxies, {})
            self.assertIsInstance(handlers[1], transport.NoRedirect)
            with self.assertRaises(transport.SmsTransportError):
                handlers[1].redirect_request(None, None, 307, "redirect", {}, "https://other.test")
            requests = []
            client._request = lambda request: requests.append(request) or {}
            args = {"token": "synthetic-token", "tenant": "tenant-fixture", "key": "odoo-sms:fixture", "correlation": "fixture"}
            client.message(**args, payload={"channel": "sms"})
            client.message(**args)
            self.assertEqual([request.method for request in requests], ["POST", "GET"])
            self.assertTrue(requests[1].full_url.endswith("/v1/communications/messages/by-idempotency"))
            self.assertIsNone(requests[1].data)
            self.assertEqual(requests[0].get_header("Idempotency-key"), requests[1].get_header("Idempotency-key"))

    def test_readback_identity_and_delivery_semantics(self):
        args = {"tenant": "tenant-fixture", "key": "odoo-sms:fixture", "correlation": "fixture", "sms_uuid": "fixture"}
        value = {"tenantId": args["tenant"], "idempotencyKey": args["key"], "correlationId": args["correlation"],
                 "metadata": {"odooSmsUuid": "fixture"}, "messageId": str(uuid4()), "channel": "sms",
                 "direction": "outbound", "status": "queued"}
        self.assertEqual(transport.validate_message(value, **args)[0], "queued")
        for field, changed in (("tenantId", "other"), ("idempotencyKey", "other"), ("correlationId", "other"),
                               ("channel", "email"), ("direction", "inbound"), ("status", "success"),
                               ("metadata", {}), ("messageId", "invalid")):
            with self.subTest(field=field), self.assertRaises(transport.SmsTransportError):
                transport.validate_message({**value, field: changed}, **args)
        with self.assertRaises(transport.SmsTransportError):
            transport.validate_message(value, **args, message_id=str(uuid4()))
        self.assertEqual(transport.STATES["queued"][0], "process")
        self.assertEqual(transport.STATES["dispatched"][0], "pending")
        self.assertEqual(transport.STATES["delivered"][0], "sent")

    def test_response_size_and_shape_are_bounded(self):
        with patch.object(transport.ssl, "create_default_context"), patch.object(transport.urllib.request, "build_opener"):
            client = transport.MiddlewareSmsClient(self.config())
            response = client.opener.open.return_value.__enter__.return_value
            response.status = 200
            for body in (b"x" * (transport.MAX_RESPONSE + 1), b"[]", b"not-json"):
                response.read.return_value = body
                with self.assertRaises(transport.SmsTransportError):
                    client._request(MagicMock())
            response.read.return_value = json.dumps({"ok": True}).encode()
            self.assertEqual(client._request(MagicMock()), {"ok": True})

    def test_delivery_flags_are_both_required(self):
        with patch.dict(transport.os.environ, {}, clear=True):
            self.assertFalse(transport.delivery_enabled())
            transport.os.environ["CODESTRA_SMS_ENABLED"] = "true"
            self.assertFalse(transport.delivery_enabled())
            transport.os.environ["ALLOW_LIVE_SMS"] = "true"
            self.assertTrue(transport.delivery_enabled())
