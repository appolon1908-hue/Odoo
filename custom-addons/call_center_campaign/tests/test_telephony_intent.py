from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestTelephonyIntent(TransactionCase):
    def test_vicidial_requires_explicit_telephony(self):
        campaign = self.env["call.center.campaign"].with_context(
            active_test=False
        ).search([], limit=1)
        self.assertTrue(campaign)
        with self.assertRaises(ValidationError):
            campaign.write({"telephony_enabled": False, "vicidial_required": True})

    def test_default_is_fail_closed(self):
        model = self.env["call.center.campaign"]
        self.assertFalse(model._fields["telephony_enabled"].default(model))
        self.assertFalse(model._fields["vicidial_required"].default(model))
