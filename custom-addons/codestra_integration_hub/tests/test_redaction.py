from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase

from ..services.canonical_json import content_hash
from ..services.redaction import redact_and_validate


class TestRedaction(TransactionCase):
    def test_nested_redaction_and_canonical_hash(self):
        clean = redact_and_validate({"password": "x", "nested": [{"Authorization": "Bearer abc"}], "note": "Bearer xyz"})
        rendered = str(clean)
        self.assertNotIn("abc", rendered)
        self.assertNotIn("xyz", rendered)
        self.assertNotIn("'x'", rendered)
        self.assertEqual(content_hash({"b": 2, "a": 1}), content_hash({"a": 1, "b": 2}))

    def test_oversized_payload_rejected(self):
        with self.assertRaises(ValidationError):
            redact_and_validate({"value": "x" * 70000})
