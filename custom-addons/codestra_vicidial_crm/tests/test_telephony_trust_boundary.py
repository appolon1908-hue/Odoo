"""Exercise RPC privacy and transport classification on the real Odoo registry."""

import contextlib
from unittest import mock

from odoo.exceptions import AccessError
from odoo.service.model import call_kw, get_public_method
from odoo.tests.common import TransactionCase

from ..models import middleware_client
from ..models.middleware_client import OriginateOutcomeUnknown, OriginateRejected


class TestTelephonyTrustBoundary(TransactionCase):
    def setUp(self):
        super().setUp()
        self.client = self.env["codestra.telephony.middleware.client"]
        self.params = self.env["ir.config_parameter"].sudo()
        self.params.set_param(
            "codestra.middleware.telephony_originate_url",
            "https://middleware.example.test/v1/telephony/calls/originate",
        )
        self.params.set_param("codestra.middleware.api_key", "synthetic-call-client")

    @contextlib.contextmanager
    def response(self, body):
        response = mock.MagicMock()
        response.read.return_value = body
        response.__enter__.return_value = response
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(middleware_client.urllib.request, "build_opener", return_value=opener):
            yield opener

    def test_rpc_cannot_invoke_service_credential_dispatch(self):
        # Exercise Odoo's real dispatcher, not just the decorator's marker.
        for client in (
            self.client,
            self.client.with_user(self.env.ref("base.public_user")),
            self.client.sudo(),
        ):
            with self.subTest(uid=client.env.uid, su=client.env.su), mock.patch.object(
                middleware_client.urllib.request, "build_opener"
            ) as build:
                with self.assertRaises(AccessError):
                    call_kw(
                        client, "originate_call",
                        ["synthetic-correlation", "synthetic-key", {}], {},
                    )
                build.assert_not_called()

    def test_governed_lead_action_remains_public(self):
        self.assertTrue(callable(get_public_method(self.env["crm.lead"], "action_click_to_call")))

    def test_internal_python_dispatch_remains_available(self):
        with self.response(b'{"dialing":"attempting","call_id":"synthetic-call"}') as opener:
            result = self.client.originate_call("synthetic-correlation", "synthetic-key", {})
        self.assertEqual(result["call_id"], "synthetic-call")
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_header("X-correlation-id"), "synthetic-correlation")
        self.assertEqual(request.get_header("Idempotency-key"), "synthetic-key")
        opener.open.assert_called_once()

    def test_ambiguous_acknowledgement_requires_reconciliation(self):
        for body in (
            b'{"dialing":"attempting","dialing":"blocked"}',
            b'{"dialing":"blocked","meta":{"a":1,"a":2}}',
            b'{"dialing":"blocked","duration":NaN}',
            b'{"dialing":"blocked","duration":1e999}',
        ):
            with self.subTest(body=body), self.response(body) as opener:
                with self.assertRaises(OriginateOutcomeUnknown):
                    self.client.originate_call("synthetic-correlation", "synthetic-key", {})
                opener.open.assert_called_once()

    def test_acknowledgement_for_another_request_is_not_applied(self):
        for body in (
            b'{"dialing":"blocked","correlation_id":"another-request"}',
            b'{"dialing":"blocked","idempotency_key":"another-request"}',
        ):
            with self.subTest(body=body), self.response(body):
                with self.assertRaises(OriginateOutcomeUnknown):
                    self.client.originate_call("synthetic-correlation", "synthetic-key", {})

    def test_invalid_request_is_rejected_before_transport(self):
        with mock.patch.object(middleware_client.urllib.request, "build_opener") as build:
            with self.assertRaises(OriginateRejected):
                self.client.originate_call("bad\r\nheader", "synthetic-key", {})
            with self.assertRaises(OriginateRejected):
                self.client.originate_call("synthetic-correlation", "synthetic-key", {"value": float("nan")})
            with self.assertRaises(OriginateRejected):
                self.client.originate_call("synthetic-correlation", "synthetic-key", {"idempotency_key": "different"})
            build.assert_not_called()
