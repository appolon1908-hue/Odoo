import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import ClassVar

from odoo import http, release
from odoo.exceptions import ValidationError
from odoo.http import request
from werkzeug.exceptions import BadRequest, Conflict, Forbidden, NotFound


class CodestraAPI(http.Controller):
    CALL_EVENTS: ClassVar = {
        "call.created": "new",
        "call.offered": "offered",
        "call.ringing": "ringing",
        "call.answered": "answering",
        "call.connected": "connected",
        "call.held": "held",
        "call.resumed": "connected",
        "call.transfer.started": "transferring",
        "call.transfer.completed": "transferred",
        "call.hangup": "ending",
        "call.completed": "completed",
        "call.ended": "completed",
        "call.failed": "failed",
        "call.missed": "missed",
        "call.recording_available": None,
        "call.disposition_required": None,
    }

    @staticmethod
    def signature(secret, timestamp, body):
        return hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()

    @staticmethod
    def timestamp_is_fresh(timestamp, now=None, tolerance=300):
        try:
            return abs((time.time() if now is None else now) - int(timestamp)) <= tolerance
        except (TypeError, ValueError):
            return False

    @http.route("/codestra/api/v1/health", type="http", auth="none", methods=["GET"], csrf=False)
    def health(self):
        return request.make_json_response(
            {
                "module_version": "19.0.3.0.0",
                "live_writes_enabled": False,
                "vicidial_read_only": True,
                "odoo_version": release.version,
            }
        )

    def _verify(self):
        timestamp = request.httprequest.headers.get("X-Codestra-Timestamp")
        signature = request.httprequest.headers.get("X-Codestra-Signature")
        key = request.httprequest.headers.get("X-Codestra-Event-ID")
        if not timestamp or not signature or not key:
            raise Forbidden("Missing integration signature headers")
        if not self.timestamp_is_fresh(timestamp):
            raise Forbidden("Expired timestamp")
        secret = request.env["ir.config_parameter"].sudo().get_param("codestra.webhook_secret")
        body = request.httprequest.get_data()
        expected = self.signature(secret or "", timestamp, body)
        if not secret or not hmac.compare_digest(expected, signature):
            raise Forbidden("Invalid signature")
        return key, body

    @http.route("/codestra/api/v1/events", type="http", auth="none", methods=["POST"], csrf=False)
    def events(self):
        key, body = self._verify()
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise BadRequest("JSON required") from exc
        if not isinstance(payload, dict) or not payload.get("event_type"):
            raise BadRequest("event_type required")
        model = request.env["codestra.integration.event"].sudo()
        digest = hashlib.sha256(body).hexdigest()
        prior = model.search([("idempotency_key", "=", key)], limit=1)
        if prior:
            if prior.payload_hash != digest:
                raise Forbidden("Idempotency payload conflict")
            return request.make_json_response({"status": "duplicate", "id": prior.id})
        record = model.create(
            {
                "event_type": payload["event_type"],
                "source_system": "external",
                "destination_system": "odoo",
                "correlation_id": payload.get("correlation_id"),
                "idempotency_key": key,
                "payload_json": json.dumps(payload, sort_keys=True),
                "payload_hash": digest,
                "state": "queued",
            }
        )
        return request.make_json_response({"status": "accepted", "id": record.id}, status=202)

    @http.route("/codestra/api/v1/call-events", type="http", auth="none", methods=["POST"], csrf=False)
    def call_events(self):
        key, body = self._verify()
        if len(body) > 262144:
            raise BadRequest("call event exceeds the size limit")
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise BadRequest("JSON required") from exc
        required = {
            "schema_version",
            "event_id",
            "event_type",
            "timestamp",
            "correlation_id",
            "tenant_id",
            "business_unit_id",
            "campaign_id",
            "call_id",
            "asterisk_uniqueid",
            "linkedid",
            "agent_id",
            "extension",
            "sequence",
            "keycloak_subject",
        }
        if not isinstance(payload, dict) or required - set(payload):
            raise BadRequest("canonical call event fields required")
        if payload.get("schema_version") != "1.0":
            raise BadRequest("unsupported call event schema version")
        if payload["event_type"] not in self.CALL_EVENTS:
            raise BadRequest("unsupported call event type")
        if (
            not isinstance(payload.get("sequence"), int)
            or isinstance(payload.get("sequence"), bool)
            or payload["sequence"] < 0
        ):
            raise BadRequest("sequence must be a nonnegative integer")
        if any(
            not isinstance(payload.get(name), str) or not payload[name].strip() or len(payload[name]) > 255
            for name in (
                "event_id",
                "correlation_id",
                "tenant_id",
                "business_unit_id",
                "campaign_id",
                "call_id",
                "asterisk_uniqueid",
                "linkedid",
                "agent_id",
                "extension",
                "keycloak_subject",
            )
        ):
            raise BadRequest("canonical identifiers must be nonempty bounded strings")
        try:
            timestamp = datetime.fromisoformat(str(payload["timestamp"]).replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("timezone required")
            payload["timestamp"] = timestamp.astimezone(timezone.utc).replace(tzinfo=None)
        except (TypeError, ValueError) as exc:
            raise BadRequest("timestamp must be an ISO-8601 value with timezone") from exc
        if key != str(payload["event_id"]):
            raise Forbidden("event identity mismatch")
        params = request.env["ir.config_parameter"].sudo()
        allowed_tenants = {
            item.strip()
            for item in (params.get_param("codestra.call_control.tenant_ids") or "").split(",")
            if item.strip()
        }
        if payload["tenant_id"] not in allowed_tenants:
            raise Forbidden("tenant rejected")
        Campaign = request.env["codestra.vicidial.campaign"].sudo()
        Agent = request.env["codestra.vicidial.agent"].sudo()
        Call = request.env["codestra.vicidial.call"].sudo()
        campaign = Campaign.search([("campaign_id", "=", payload["campaign_id"])], limit=1)
        agent = Agent.search(
            [
                ("vicidial_user", "=", str(payload["agent_id"])),
                ("phone_login", "=", str(payload["extension"])),
                ("active", "=", True),
                ("tenant_id", "=", payload["tenant_id"]),
            ],
            limit=1,
        )
        if (
            not campaign
            or not agent
            or campaign not in agent.campaign_ids
            or not agent.odoo_user_id.keycloak_subject
            or agent.odoo_user_id.keycloak_subject != str(payload["keycloak_subject"])
        ):
            raise Forbidden("agent campaign extension mapping rejected")
        call = Call.search([("call_id", "=", str(payload["call_id"]))], limit=1)
        if call and (
            call.tenant_id != payload["tenant_id"]
            or call.agent_id != agent
            or call.campaign_id != campaign
            or call.extension != str(payload["extension"])
            or call.keycloak_subject != str(payload["keycloak_subject"])
        ):
            raise Forbidden("existing call binding conflict")
        if not call and payload["event_type"] in {
            "call.answered",
            "call.connected",
            "call.held",
            "call.resumed",
            "call.transfer.started",
            "call.transfer.completed",
            "call.hangup",
            "call.completed",
            "call.ended",
            "call.recording_available",
            "call.disposition_required",
        }:
            raise NotFound("call must be established before this lifecycle event")
        if not call:
            number = payload.get("caller_number") or payload.get("destination_number")
            match = (
                Call.match_customer(number, payload["campaign_id"])
                if number
                else {"normalized_number": False, "match": "none", "matches": []}
            )
            exact = match["match"] == "exact"
            lead_match = next((row for row in match["matches"] if exact and row["model"] == "lead"), None)
            partner_match = next((row for row in match["matches"] if exact and row["model"] == "partner"), None)
            values = {
                "name": f"{payload['event_type']} {payload['call_id']}",
                "call_id": str(payload["call_id"]),
                "correlation_id": payload["correlation_id"],
                "asterisk_uniqueid": payload["asterisk_uniqueid"],
                "uniqueid": payload["asterisk_uniqueid"],
                "linkedid": payload["linkedid"],
                "tenant_id": payload["tenant_id"],
                "keycloak_subject": str(payload["keycloak_subject"]),
                "business_unit_id": payload["business_unit_id"],
                "campaign_id": campaign.id,
                "campaign_code": payload["campaign_id"],
                "agent_id": agent.id,
                "vicidial_user": agent.vicidial_user,
                "extension": payload["extension"],
                "direction": payload.get("direction") or "inbound",
                "caller_id": payload.get("caller_number"),
                "destination": payload.get("destination_number"),
                "original_number": number,
                "normalized_number": match["normalized_number"],
                "match_status": match["match"],
                "lead_id": lead_match and lead_match["id"],
                "crm_lead_id": lead_match and lead_match["id"],
                "customer_id": partner_match and partner_match["id"],
                "state": "new",
                "sequence": 0,
                "source_system": "asterisk",
                "idempotency_key": "call:" + str(payload["call_id"]),
            }
            call = Call.create(values)
        try:
            result = call.apply_authoritative_event(
                {
                    **payload,
                    "state": self.CALL_EVENTS[payload["event_type"]],
                }
            )
        except ValidationError as exc:
            raise Conflict(str(exc)) from exc
        return request.make_json_response(result, status=200 if result.get("duplicate") else 202)

    @http.route("/codestra/api/v1/sync/preview", type="jsonrpc", auth="user", methods=["POST"], csrf=False)
    def preview(self):
        return {"read_only": True, "changes": []}
