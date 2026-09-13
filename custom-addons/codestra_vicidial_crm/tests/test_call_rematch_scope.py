from inspect import signature
from pathlib import Path
from unittest.mock import patch

from odoo.modules.module import get_module_path
from odoo.tests.common import TransactionCase

from ..controllers.call_control import CallControlAPI
from ..controllers.call_control_scope import ScopedCallControlAPI
from ..models.call_control import ALLOWED_TRANSITIONS


class TestCallRematchScope(TransactionCase):
    def test_offered_event_can_progress_to_ringing(self):
        self.assertIn("ringing", ALLOWED_TRANSITIONS["offered"])

    def test_browser_rematch_carries_assigned_call_scope(self):
        module = Path(get_module_path("codestra_vicidial_crm"))
        browser = (
            module / "static" / "src" / "js" / "call_popup.js"
        ).read_text(encoding="utf-8")
        self.assertIn("call_id: payload.call_id", browser)
        self.assertIn(
            "business_unit_id: payload.business_unit",
            browser,
        )

    def test_pre_dial_match_delegates_without_call_id(self):
        expected = {"match": "exact"}
        with patch.object(CallControlAPI, "match", return_value=expected) as match:
            result = ScopedCallControlAPI().match(
                "+18496582053",
                campaign_code="TEST_SYN",
            )

        self.assertEqual(result, expected)
        match.assert_called_once_with(
            "+18496582053",
            campaign_code="TEST_SYN",
        )

    def test_dialpad_outbound_contract_is_pre_identification_compatible(self):
        parameters = signature(CallControlAPI.outbound).parameters
        self.assertIsNone(parameters["lead_id"].default)
        self.assertIsNone(parameters["destination"].default)
        self.assertEqual(parameters["campaign_id"].default, "TEST_SYN")
        self.assertIsNone(parameters["idempotency_key"].default)

    def test_controller_rebinds_untrusted_browser_scope_to_owned_call(self):
        module = Path(get_module_path("codestra_vicidial_crm"))
        controller = (
            module / "controllers" / "call_control_scope.py"
        ).read_text(encoding="utf-8")
        required = (
            "call = self._owned_call(call_id)",
            "supplied_unit != call.business_unit_id",
            "campaign_code != canonical_campaign",
            "normalized != expected_number",
            "business_unit_id=units.id",
        )
        for token in required:
            self.assertIn(token, controller)
