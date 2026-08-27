import json
import os

from odoo import SUPERUSER_ID, http
from odoo.exceptions import ValidationError
from odoo.http import request

from .contract import ContractError, validate_apply
from .service_auth import (
    AuthenticationError,
    verify,
)

ACTIONS = {
    "CREATE_LEAD",
    "UPDATE_ALLOWLISTED_FIELDS",
    "ASSIGN_AUTHORIZED_TEAM",
    "ASSIGN_AUTHORIZED_USER",
    "CHANGE_AUTHORIZED_STAGE",
    "CREATE_INTERNAL_CALLBACK_ACTIVITY",
}
SWITCHES = {
    "CREATE_LEAD": "LEAD_CREATE_ENABLED",
    "UPDATE_ALLOWLISTED_FIELDS": "LEAD_UPDATE_ENABLED",
    "ASSIGN_AUTHORIZED_TEAM": "LEAD_ASSIGNMENT_ENABLED",
    "ASSIGN_AUTHORIZED_USER": "LEAD_ASSIGNMENT_ENABLED",
    "CHANGE_AUTHORIZED_STAGE": "LEAD_STATUS_CHANGE_ENABLED",
    "CREATE_INTERNAL_CALLBACK_ACTIVITY": "LEAD_CALLBACK_CREATE_ENABLED",
}
def enabled(name):
    return os.getenv(name, "false").lower() == "true"


class LeadAutomationController(http.Controller):
    @http.route(
        "/codestra/api/v1/leads/automation/apply",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
    )
    def apply(self):
        raw = request.httprequest.get_data(cache=True)
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return request.make_json_response({"error": "invalid JSON"}, status=400)
        headers = {
            name: request.httprequest.headers.get(name, "")
            for name in __import__(
                "odoo.addons.codestra_lead_automation.controllers.service_auth",
                fromlist=["HEADERS"],
            ).HEADERS
        }
        # Secrets are injected into the process and are never persisted in Odoo.
        secret = os.getenv("ODOO_LEAD_AUTOMATION_HMAC_SECRET", "").encode()
        environment = os.getenv("ODOO_LEAD_AUTOMATION_ENVIRONMENT", "staging")
        try:
            idem = verify(
                method=request.httprequest.method,
                path=request.httprequest.path,
                query_string=request.httprequest.query_string,
                body=raw,
                headers=headers,
                secret=secret,
                expected_environment=environment,
                used_nonces=set(),
            )
        except AuthenticationError as exc:
            return request.make_json_response({"error": str(exc)}, status=401)
        # auth="none" intentionally admits only the verified HMAC boundary.
        # Bind the transaction to Odoo's system user after verification so
        # ORM flushes cannot inherit an anonymous/empty user recordset.
        request.update_env(user=SUPERUSER_ID)
        try:
            request.env["codestra.lead.automation.nonce"].consume(
                environment, headers["X-Service-Identity"], headers["X-Codestra-Nonce"]
            )
        except ValidationError:
            return request.make_json_response({"error": "nonce replay"}, status=401)
        try:
            validate_apply(body)
        except ContractError as exc:
            return request.make_json_response({"error": str(exc)}, status=422)
        if idem != body["idempotency_key"] or body["environment"] != environment:
            return request.make_json_response(
                {"error": "request binding mismatch"}, status=422
            )
        if not enabled("ODOO_LEAD_APPLY_ENABLED"):
            return request.make_json_response(
                {"error": "lead apply disabled"}, status=403
            )
        action = body.get("automation_action")
        if action not in ACTIONS or not enabled(SWITCHES[action]):
            return request.make_json_response({"error": "action disabled"}, status=403)
        receipt = (
            request.env["codestra.lead.automation.receipt"]
            .sudo()
            .search(
                [("environment", "=", environment), ("idempotency_key", "=", idem)],
                limit=1,
            )
        )
        if receipt:
            if receipt.request_hash != headers["X-Codestra-Content-SHA256"]:
                return request.make_json_response(
                    {"error": "idempotency conflict"}, status=409
                )
            response = dict(receipt.acknowledgement_json)
            response["idempotent_replay"] = True
            return request.make_json_response(response)
        response = (
            request.env["codestra.lead.automation.receipt"]
            .sudo()
            .apply_authorized(
                body, environment, idem, headers["X-Codestra-Content-SHA256"]
            )
        )
        return request.make_json_response(response)
