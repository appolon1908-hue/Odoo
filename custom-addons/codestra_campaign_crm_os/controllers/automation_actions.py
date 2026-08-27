import json

from odoo import http
from odoo.addons.call_center_campaign.controllers.integration_api import (
    IntegrationConflict,
    IntegrationRejected,
    _assert_scope,
    _body,
    _handle_errors,
    _json_response,
)
from odoo.http import request
from odoo.exceptions import AccessError


REQUIRED_FIELDS = {
    "schema_version", "event_id", "correlation_id", "causation_id",
    "idempotency_key", "environment", "business_unit_public_id",
    "campaign_public_id", "actor_type", "actor_id", "workflow_key",
    "execution_id", "actions",
}


class CodestraCampaignAutomationActionController(http.Controller):
    @http.route(
        "/api/v1/integration/campaign-actions", type="http", auth="none",
        methods=["POST"], csrf=False,
    )
    def apply_campaign_actions(self):
        def operation():
            claims, body, request_hash = _body(
                {"odoo.campaign.actions.apply"}, REQUIRED_FIELDS
            )
            if set(body) != REQUIRED_FIELDS:
                raise IntegrationRejected("unexpected campaign action fields")
            if body["schema_version"] != "1.0":
                raise IntegrationRejected("unsupported campaign action schema")
            if body["actor_type"] not in {"AI", "SYSTEM"}:
                raise IntegrationRejected("service actions cannot impersonate a human")
            if not isinstance(body["actions"], list) or not body["actions"]:
                raise IntegrationRejected("one or more actions are required")
            if len(body["actions"]) > 100:
                raise IntegrationRejected("too many actions")
            _assert_scope(
                claims, str(body["environment"]).upper(),
                body["business_unit_public_id"], body["campaign_public_id"],
            )
            receipt_model = request.env["codestra.automation.action.receipt"].sudo()
            receipt = receipt_model.search(
                [("idempotency_key", "=", body["idempotency_key"])], limit=1
            )
            if receipt:
                if receipt.request_hash != request_hash:
                    raise IntegrationConflict("campaign action idempotency conflict")
                return _json_response(json.loads(receipt.response_json), 200)
            try:
                result = request.env["codestra.campaign.action.service"].sudo().apply(body)
            except AccessError as exc:
                raise IntegrationRejected(str(exc)) from exc
            receipt = receipt_model.create({
                "idempotency_key": body["idempotency_key"],
                "event_id": body["event_id"], "execution_id": body["execution_id"],
                "request_hash": request_hash, "correlation_id": body["correlation_id"],
                "campaign_public_id": body["campaign_public_id"],
                "response_json": "{}",
            })
            result["receipt_id"] = receipt.receipt_uuid
            receipt.with_context(codestra_receipt_finalize=True).write({
                "response_json": json.dumps(result, sort_keys=True, separators=(",", ":"))
            })
            return _json_response(result, 200)

        return _handle_errors(operation)
