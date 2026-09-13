import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "custom-addons/codestra_email_middleware/transport.py"
spec = importlib.util.spec_from_file_location("email_middleware_transport", PATH)
transport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transport)


class TestEmailMiddlewareTransport(unittest.TestCase):
    def config(self, **changes):
        values = {
            "API_BASE_URL": "https://middleware.example.test",
            "TOKEN_URL": "https://auth.example.test/token",
            "CLIENT_SECRET_FILE": "/run/secrets/fixture",
            "CA_FILE": "/run/secrets/ca",
            "TENANT_ID": "tenant-fixture",
            "COMPANY_ID": "1",
            "SENDER": "sender@example.com",
        }
        values.update(changes)
        return transport.configuration({
            "CODESTRA_EMAIL_" + key: value for key, value in values.items()
        })

    def test_transport_requires_https_files_and_bounded_scope(self):
        self.assertEqual(self.config()["company_id"], 1)
        for field, value in (
            ("API_BASE_URL", "http://middleware.example.test"),
            ("API_BASE_URL", "https://user:secret@example.test"),
            ("API_BASE_URL", "https://example.test/unexpected"),
            ("TOKEN_URL", "http://keycloak:8080/token"),
            ("CA_FILE", "relative.pem"),
            ("COMPANY_ID", "0"),
            ("TENANT_ID", "tenant\nheader"),
            ("SENDER", "not-an-address"),
        ):
            with self.subTest(field=field), self.assertRaises(
                transport.EmailTransportError
            ):
                self.config(**{field: value})

    def test_no_proxy_redirect_and_post_then_read_only_contract(self):
        config = self.config()
        with patch.object(transport.ssl, "create_default_context") as tls, \
                patch.object(transport.urllib.request, "build_opener") as opener:
            client = transport.MiddlewareEmailClient(config)
            tls.assert_called_once_with(cafile=config["ca_file"])
            handlers = opener.call_args.args
            self.assertEqual(handlers[0].proxies, {})
            self.assertIsInstance(handlers[1], transport.NoRedirect)
            requests = []
            client._request = lambda request: requests.append(request) or {}
            args = {
                "token": "synthetic-token", "tenant": "tenant-fixture",
                "key": "odoo-email:fixture", "correlation": "fixture",
            }
            client.message(**args, payload={"channel": "email"})
            client.message(**args)
            client.events(**args, message_id=str(uuid4()))
            self.assertEqual(
                [request.method for request in requests], ["POST", "GET", "GET"]
            )
            self.assertTrue(
                requests[1].full_url.endswith(
                    "/v1/communications/messages/by-idempotency"
                )
            )

    def test_readback_identity_and_precise_event_state(self):
        args = {
            "tenant": "tenant-fixture", "key": "odoo-email:fixture",
            "correlation": "fixture", "mail_id": 42,
        }
        value = {
            "tenantId": args["tenant"], "idempotencyKey": args["key"],
            "correlationId": args["correlation"],
            "metadata": {"odooMailId": "42"}, "messageId": str(uuid4()),
            "channel": "email", "direction": "outbound", "status": "failed",
        }
        state, message_id, _ = transport.validate_message(value, **args)
        self.assertEqual(state, "failed")
        self.assertEqual(
            transport.state_from_events(
                {"items": [{"type": "klyrow.email.complained"}]}, state
            ),
            "complained",
        )
        self.assertEqual(
            transport.state_from_events(
                {"items": [
                    {"type": "klyrow.email.delivered"},
                    {"type": "klyrow.email.bounced"},
                ]},
                "provider_accepted",
            ),
            "delivered",
        )
        self.assertEqual(
            transport.state_from_events(
                {"items": [
                    {"type": "klyrow.email.delivered"},
                    {"type": "klyrow.email.complained"},
                ]},
                "provider_accepted",
            ),
            "complained",
        )
        with self.assertRaises(transport.EmailTransportError):
            transport.validate_message({**value, "tenantId": "other"}, **args)
        with self.assertRaises(transport.EmailTransportError):
            transport.validate_message(value, **args, message_id=str(uuid4()))

    def test_response_size_and_shape_are_bounded(self):
        with patch.object(transport.ssl, "create_default_context"), \
                patch.object(transport.urllib.request, "build_opener"):
            client = transport.MiddlewareEmailClient(self.config())
            response = client.opener.open.return_value.__enter__.return_value
            response.status = 200
            for body in (
                b"x" * (transport.MAX_RESPONSE + 1), b"[]", b"not-json"
            ):
                response.read.return_value = body
                with self.assertRaises(transport.EmailTransportError):
                    client._request(MagicMock())
            response.read.return_value = json.dumps({"ok": True}).encode()
            self.assertEqual(client._request(MagicMock()), {"ok": True})

    def test_delivery_flags_and_fixed_client_identity(self):
        with patch.dict(transport.os.environ, {}, clear=True):
            self.assertFalse(transport.delivery_enabled())
            transport.os.environ["CODESTRA_EMAIL_ENABLED"] = "true"
            self.assertFalse(transport.delivery_enabled())
            transport.os.environ["ALLOW_LIVE_EMAIL"] = "true"
            self.assertTrue(transport.delivery_enabled())
        with patch.object(transport.ssl, "create_default_context"), \
                patch.object(transport.urllib.request, "build_opener"), \
                patch("builtins.open", mock_open(read_data="synthetic-secret")):
            client = transport.MiddlewareEmailClient(self.config())
            client._request = MagicMock(return_value={"access_token": "token"})
            self.assertEqual(client.token(), "token")
            form = transport.urllib.parse.parse_qs(
                client._request.call_args.args[0].data.decode()
            )
            self.assertEqual(form["client_id"], ["odoo-email"])
            self.assertNotIn("scope", form)
