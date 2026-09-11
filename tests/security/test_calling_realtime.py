"""Exercise the real generated read-side transport without Odoo or network effects."""
import importlib.util
import json
import unittest
from datetime import datetime, timedelta, timezone
from email.message import Message
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('calling_readside', ROOT / 'custom-addons/codestra_vicidial_crm/models/calling_realtime.py')
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)
OP = '11111111-1111-4111-8111-111111111111'
CORR = '22222222-2222-4222-8222-222222222222'


def ticket(**overrides):
    value = {'ticket': 'synthetic-one-use-ticket-for-tests-0000',
             'expires_at': (datetime.now(timezone.utc) + timedelta(seconds=45)).isoformat(),
             'websocket_url': 'wss://api.codestra.co/ws/agent', 'contract_digest': client.SCHEMA['digest']}
    return dict(value, **overrides)


class CallingTransportTest(unittest.TestCase):
    def response(self, value, status=201, content_type='application/json'):
        response = MagicMock()
        response.status = status
        response.headers = Message()
        response.headers['Content-Type'] = content_type
        response.read.return_value = value if isinstance(value, bytes) else json.dumps(value).encode()
        response.__enter__.return_value = response
        opener = MagicMock()
        opener.open.return_value = response
        patcher = patch.object(client.urllib.request, 'build_opener', return_value=opener)
        patcher.start(); self.addCleanup(patcher.stop)
        return opener, response

    def create(self, **overrides):
        args = dict(token='synthetic-user-token', campaign_id='SYN-CAMPAIGN', resume_cursor=0,
                    correlation_id=CORR, idempotency_key='synthetic-ticket-request-0001')
        return client.create_session(**dict(args, **overrides))

    def test_session_uses_exact_canonical_route_headers_and_selection_only(self):
        opener, response = self.response(ticket())
        self.assertEqual(self.create()['contract_digest'], client.SCHEMA['digest'])
        req = opener.open.call_args.args[0]
        self.assertEqual(req.full_url, 'https://api.codestra.co/api/v1/realtime/sessions')
        self.assertEqual(req.get_method(), 'POST')
        self.assertEqual(req.get_header('Authorization'), 'Bearer synthetic-user-token')
        self.assertEqual(req.get_header('X-correlation-id'), CORR)
        self.assertEqual(req.get_header('Idempotency-key'), 'synthetic-ticket-request-0001')
        self.assertEqual(json.loads(req.data), {'campaign_id': 'SYN-CAMPAIGN', 'resume_cursor': 0})
        response.read.assert_called_once_with(client.MAX_BYTES + 1)
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 5)

    def test_invalid_input_never_sends_a_request(self):
        for args in ({'campaign_id': '*'}, {'campaign_id': 'x.y'}, {'resume_cursor': True},
                     {'resume_cursor': -1}, {'resume_cursor': 2**53}, {'correlation_id': 'bad'},
                     {'token': 'bad\nheader'}, {'idempotency_key': 'short'}):
            with self.subTest(args=args):
                opener, _ = self.response(ticket())
                with self.assertRaises(client.RealtimeUnavailable): self.create(**args)
                opener.open.assert_not_called()

    def test_old_protocol_and_wrong_scope_digest_or_destination_are_rejected(self):
        for value in ({'ws_url': 'wss://api.codestra.co/ws/agent', 'ticket': 'a'*40},
                      ticket(websocket_url='wss://untrusted.invalid/ws/agent'),
                      ticket(websocket_url='wss://api.codestra.co/ws/agent?ticket=hidden'),
                      ticket(contract_digest='0'*64), ticket(ticket='a'*31), ticket(ticket='a'*32+'\n'),
                      ticket(expires_at='2020-01-01T00:00:00Z'),
                      ticket(expires_at=(datetime.now(timezone.utc)+timedelta(seconds=90)).isoformat()),
                      ticket(expires_at='2026-02-31T00:00:00Z'), ticket(extra='field')):
            with self.subTest(value=value):
                self.response(value)
                with self.assertRaises(client.RealtimeUnavailable): self.create()

    def test_malformed_oversized_and_duplicate_json_are_rejected(self):
        for raw in (b'[]', b'{', b'x'*(client.MAX_BYTES+1), b'{"ticket":"a","ticket":"b"}', b'{"ticket":NaN}'):
            with self.subTest(raw=raw[:50]):
                self.response(raw)
                with self.assertRaises(client.RealtimeUnavailable): self.create()

    def test_failure_is_redacted_without_retry(self):
        opener, _ = self.response(ticket())
        opener.open.side_effect = OSError('synthetic-secret-that-must-not-be-shown')
        with self.assertRaises(client.RealtimeUnavailable) as error: self.create()
        self.assertNotIn('synthetic-secret', str(error.exception))
        self.assertIsNone(error.exception.__cause__)
        opener.open.assert_called_once()

    def test_wrong_http_status_or_content_type_is_rejected(self):
        for status, content_type in [(200, 'application/json'), (302, 'application/json'), (201, 'text/html')]:
            with self.subTest(status=status, content_type=content_type):
                self.response(ticket(), status, content_type)
                with self.assertRaises(client.RealtimeUnavailable): self.create()

    def test_redirect_handler_never_forwards_credentials(self):
        self.assertIsNone(client.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://elsewhere.invalid'))

    def test_operation_reads_are_bound_and_never_mutate(self):
        operation = {'operation_id': OP, 'state': 'COMPLETED', 'external_effect': True, 'calls_placed': 1}
        opener, _ = self.response(operation, 200)
        self.assertEqual(client.read_operation('synthetic-user-token', OP, CORR), operation)
        req = opener.open.call_args.args[0]
        self.assertEqual(req.get_method(), 'GET'); self.assertIsNone(req.data)
        self.assertEqual(req.full_url, 'https://api.codestra.co/v1/telephony/operations/'+OP)
        self.assertIsNone(req.get_header('Idempotency-key'))

    def test_wrong_operation_and_non_integer_call_counters_are_rejected(self):
        for override in ({'operation_id': CORR}, {'calls_placed': True}, {'calls_placed': -1}, {'state': 'call_placed'}):
            self.response(dict({'operation_id': OP, 'state': 'COMPLETED', 'external_effect': False, 'calls_placed': 0}, **override), 200)
            with self.assertRaises(client.RealtimeUnavailable): client.read_operation('synthetic-user-token', OP, CORR)

    def test_generated_files_match_pinned_authority(self):
        from scripts.generate_calling_client_schema import check
        check()


if __name__ == '__main__': unittest.main()
