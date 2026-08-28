from odoo.tests.common import TransactionCase

from ..controllers.api import CodestraAPI


class TestWebhookSecurity(TransactionCase):
    def test_signature_and_replay_window(self):
        body = b'{"event_type":"test"}'
        digest = CodestraAPI.signature('secret', '1000', body)
        self.assertEqual(len(digest), 64)
        self.assertTrue(CodestraAPI.timestamp_is_fresh('1000', now=1200))
        self.assertFalse(CodestraAPI.timestamp_is_fresh('1000', now=1400))
        self.assertFalse(CodestraAPI.timestamp_is_fresh('invalid', now=1000))
