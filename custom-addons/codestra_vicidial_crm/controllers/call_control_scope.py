"""Business-unit-bound browser rematching for assigned calls."""

from odoo import http
from odoo.exceptions import AccessError
from odoo.http import request

from .call_control import CallControlAPI


class ScopedCallControlAPI(CallControlAPI):
    @http.route(
        "/codestra/call-control/v1/match",
        type="jsonrpc",
        auth="user",
        methods=["POST"],
    )
    def match(
        self,
        number,
        call_id,
        campaign_code=None,
        business_unit_id=None,
    ):
        call = self._owned_call(call_id)
        Call = request.env["codestra.vicidial.call"]

        canonical_campaign = (
            call.campaign_code or call.campaign_id.campaign_id
        )
        supplied_unit = str(business_unit_id or "").strip()
        if (
            not call.business_unit_id
            or supplied_unit != call.business_unit_id
            or campaign_code != canonical_campaign
        ):
            raise AccessError(
                "Call rematch scope does not match the assigned call."
            )

        units = request.env["call.center.business.unit"].search(
            [
                ("code", "=", call.business_unit_id),
                ("active", "=", True),
            ],
            limit=2,
        )
        if (
            len(units) != 1
            or units not in request.env.user.call_center_business_unit_ids
            or units.company_id not in request.env.user.company_ids
        ):
            raise AccessError(
                "Call business-unit authorization is invalid."
            )

        normalized = Call.normalize_number(number)
        expected_number = call.normalized_number
        if not expected_number:
            source_number = call.caller_id or call.destination
            expected_number = (
                Call.normalize_number(source_number)
                if source_number
                else False
            )
        if not expected_number or normalized != expected_number:
            raise AccessError(
                "Call rematch number does not match the assigned call."
            )

        return Call.match_customer(
            normalized,
            canonical_campaign,
            business_unit_id=units.id,
        )
