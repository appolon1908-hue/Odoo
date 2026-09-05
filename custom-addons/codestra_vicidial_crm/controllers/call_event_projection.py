from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from datetime import datetime, timezone
from typing import ClassVar

from odoo import http
from odoo.exceptions import AccessError, ValidationError
from odoo.http import request
from werkzeug.exceptions import BadRequest, Forbidden, NotFound


class CodestraCallEventProjectionAPI(http.Controller):
    PATH = "/codestra/middleware/v1/call-events"
    STATUS_PATH = "/codestra/middleware/v1/call-events/<string:event_id>/status"
    MAX_BODY_BYTES = 262144
    SAFE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,255}$")
    CALL_EVENTS: ClassVar[dict[str, str]] = {
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
        "call.failed": "failed",
        "call.missed": "missed",
    }
    REQUIRED_FIELDS = {
        "schema_version", "event_id", "event_type", "timestamp",
        "correlation_id", "tenant_id", "business_unit_id", "campaign_id",
        "call_id", "asterisk_uniqueid", "linkedid", "agent_id", "extension",
        "sequence", "keycloak_subject", "synthetic_test", "direction",
    }
    OPTIONAL_FIELDS = {
        "caller_number", "destination_number", "talk_duration", "duration",
        "transfer_destination", "transfer_type", "hangup_cause",
        "hangup_cause_code",
    }

    @staticmethod
    def signature(secret, timestamp, event_id, method, path, tenant_id, correlation_id, body):
        canonical = b"\n".join(
            (
                timestamp.encode(), event_id.encode(), method.upper().encode(),
                path.encode(), tenant_id.encode(), correlation_id.encode(),
                event_id.encode(), body,
            )
        )
        return hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()

    @staticmethod
    def timestamp_is_fresh(timestamp, now=None, tolerance=300):
        try:
            return abs((time.time() if now is None else now) - int(timestamp)) <= tolerance
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _lock_agent_call_scope(agent_id):
        """Serialize every lifecycle mutation for the authoritative mapped agent."""
        request.env.cr.execute(
            "SELECT id FROM codestra_vicidial_agent WHERE id=%s FOR UPDATE",
            [agent_id],
        )

    @staticmethod
    def _conflict_response(
        payload,
        *,
        error,
        retryable,
        detail,
        expected_sequence=None,
        current_sequence=None,
    ):
        evidence = {
            "error": error,
            "retryable": bool(retryable),
            "detail": str(detail)[:512],
            "event_id": str(payload["event_id"]),
            "tenant_id": str(payload["tenant_id"]),
            "call_id": str(payload["call_id"]),
            "event_type": str(payload["event_type"]),
            "sequence": int(payload["sequence"]),
            "recorded": False,
        }
        if expected_sequence is not None:
            evidence["expected_sequence"] = int(expected_sequence)
        if current_sequence is not None:
            evidence["current_sequence"] = int(current_sequence)
        return request.make_json_response(evidence, status=409)

    def _authenticate(self, body):
        headers = request.httprequest.headers
        timestamp = headers.get("X-Codestra-Timestamp", "")
        event_id = headers.get("X-Codestra-Event-ID", "")
        supplied = headers.get("X-Codestra-Signature", "")
        tenant_id = headers.get("X-Tenant-ID", "")
        correlation_id = headers.get("X-Correlation-ID", "")
        idempotency_key = headers.get("Idempotency-Key", "")
        if not all((timestamp, event_id, supplied, tenant_id, correlation_id, idempotency_key)):
            raise Forbidden("Missing call-event projection authentication")
        if not supplied.startswith("sha256="):
            raise Forbidden("Invalid call-event signature format")
        if idempotency_key != event_id:
            raise Forbidden("Call-event idempotency identity mismatch")
        if not self.timestamp_is_fresh(timestamp):
            raise Forbidden("Expired call-event projection timestamp")
        params = request.env["ir.config_parameter"].sudo()
        allowed_tenants = {
            item.strip()
            for item in (params.get_param("codestra.call_control.tenant_ids") or "").split(",")
            if item.strip()
        }
        if tenant_id not in allowed_tenants:
            raise Forbidden("Call-event tenant rejected")
        tenant_scope = "codestra.middleware.tenant." + tenant_id + "."
        secret = (
            params.get_param(tenant_scope + "call_event_hmac_secret")
            or params.get_param("codestra.call_event.inbound_hmac_secret")
        )
        expected = self.signature(
            secret or "", timestamp, event_id, request.httprequest.method,
            request.httprequest.path, tenant_id, correlation_id, body,
        )
        if not secret or not hmac.compare_digest(expected, supplied.removeprefix("sha256=")):
            raise Forbidden("Invalid call-event projection signature")
        try:
            user_id = int(
                params.get_param(tenant_scope + "call_event_service_user_id")
                or params.get_param("codestra.call_event.service_user_id", "0")
            )
        except (TypeError, ValueError) as exc:
            raise Forbidden("Invalid call-event service identity") from exc
        user = request.env["res.users"].sudo().browse(user_id).exists()
        group = request.env.ref(
            "codestra_vicidial_crm.group_call_event_projection_service"
        )
        if not user or not user.active or group not in user.group_ids:
            raise Forbidden("Call-event service identity rejected")
        request.update_env(user=user.id)
        return {
            "event_id": event_id,
            "tenant_id": tenant_id,
            "correlation_id": correlation_id,
        }

    def _payload(self, body):
        if len(body) > self.MAX_BODY_BYTES:
            raise BadRequest("call event exceeds the size limit")
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise BadRequest("JSON required") from exc
        allowed = self.REQUIRED_FIELDS | self.OPTIONAL_FIELDS
        if not isinstance(payload, dict) or self.REQUIRED_FIELDS - set(payload):
            raise BadRequest("canonical call-event fields required")
        if set(payload) - allowed:
            raise BadRequest("unsupported call-event fields")
        if payload.get("schema_version") != "1.0":
            raise BadRequest("unsupported call-event schema version")
        if payload.get("event_type") not in self.CALL_EVENTS:
            raise BadRequest("unsupported call-event type")
        if type(payload.get("synthetic_test")) is not bool:
            raise BadRequest("synthetic_test must be boolean")
        if payload.get("direction") not in {"inbound", "outbound"}:
            raise BadRequest("unsupported call direction")
        if (
            not isinstance(payload.get("sequence"), int)
            or isinstance(payload.get("sequence"), bool)
            or not 1 <= payload["sequence"] <= 1_000_000
        ):
            raise BadRequest("sequence must be an integer between 1 and 1000000")
        for name in (
            "event_id", "correlation_id", "tenant_id", "business_unit_id",
            "campaign_id", "call_id", "asterisk_uniqueid", "linkedid",
            "agent_id", "extension", "keycloak_subject",
        ):
            value = payload.get(name)
            if not isinstance(value, str) or not self.SAFE_ID.fullmatch(value):
                raise BadRequest(f"invalid canonical identifier: {name}")
        for name in ("talk_duration", "duration"):
            value = payload.get(name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 86400
            ):
                raise BadRequest(f"invalid {name}")
        try:
            timestamp = datetime.fromisoformat(str(payload["timestamp"]).replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("timezone required")
        except (TypeError, ValueError) as exc:
            raise BadRequest("timestamp must include an ISO-8601 timezone") from exc
        payload["timestamp"] = timestamp.astimezone(timezone.utc).replace(tzinfo=None)
        return payload

    @staticmethod
    def _evidence(payload, result):
        value = dict(result)
        value.update(
            {
                "event_id": str(payload["event_id"]),
                "tenant_id": str(payload["tenant_id"]),
                "call_id": str(payload["call_id"]),
                "event_type": str(payload["event_type"]),
                "sequence": int(payload["sequence"]),
                "recorded": True,
            }
        )
        return value

    @http.route(PATH, type="http", auth="none", methods=["POST"], csrf=False)
    def project(self):
        body = request.httprequest.get_data()
        auth = self._authenticate(body)
        payload = self._payload(body)
        if auth["event_id"] != payload["event_id"]:
            raise Forbidden("event identity mismatch")
        if auth["tenant_id"] != payload["tenant_id"]:
            raise Forbidden("tenant identity mismatch")
        if auth["correlation_id"] != payload["correlation_id"]:
            raise Forbidden("correlation identity mismatch")
        try:
            request.env["codestra.call.event.projection.policy"].sudo().authorize_payload(payload)
        except AccessError as exc:
            raise Forbidden(str(exc)) from exc

        BusinessUnit = request.env["call.center.business.unit"].sudo()
        Campaign = request.env["codestra.vicidial.campaign"].sudo()
        Agent = request.env["codestra.vicidial.agent"].sudo()
        Call = request.env["codestra.vicidial.call"].sudo()
        Event = request.env["codestra.vicidial.call.event"].sudo()
        business_unit = BusinessUnit.search(
            [
                ("code", "=", payload["business_unit_id"]),
                ("active", "=", True),
            ],
            limit=1,
        )
        campaign = Campaign.search([("campaign_id", "=", payload["campaign_id"])], limit=1)
        agent = Agent.search(
            [
                ("vicidial_user", "=", payload["agent_id"]),
                ("phone_login", "=", payload["extension"]),
                ("active", "=", True),
                ("tenant_id", "=", payload["tenant_id"]),
            ],
            limit=1,
        )
        agent_user = agent.odoo_user_id if agent else request.env["res.users"]
        if (
            not business_unit
            or not campaign
            or not agent
            or not agent_user
            or business_unit not in agent_user.call_center_business_unit_ids
            or business_unit.company_id not in agent_user.company_ids
            or campaign not in agent.campaign_ids
            or not agent_user.keycloak_subject
            or agent_user.keycloak_subject != payload["keycloak_subject"]
        ):
            raise Forbidden("agent campaign extension business-unit mapping rejected")

        self._lock_agent_call_scope(agent.id)
        call = Call.search([("call_id", "=", payload["call_id"])], limit=1)
        prior = Event.search(
            [("idempotency_key", "=", payload["event_id"])],
            limit=1,
        )
        if prior and (not call or prior.call_id != call):
            return self._conflict_response(
                payload,
                error="event_identity_conflict",
                retryable=False,
                detail="event ID is already bound to a different call",
            )
        if call and (
            call.tenant_id != payload["tenant_id"]
            or call.business_unit_id != payload["business_unit_id"]
            or call.correlation_id != payload["correlation_id"]
            or call.agent_id != agent
            or call.campaign_id != campaign
            or call.extension != payload["extension"]
            or call.keycloak_subject != payload["keycloak_subject"]
            or call.linkedid != payload["linkedid"]
            or call.asterisk_uniqueid != payload["asterisk_uniqueid"]
        ):
            raise Forbidden("existing call binding conflict")
        if not call and payload["event_type"] not in {
            "call.created", "call.offered", "call.ringing"
        }:
            raise NotFound("call must be established before this lifecycle event")

        if not prior:
            expected_sequence = (call.sequence + 1) if call else 1
            if payload["sequence"] != expected_sequence:
                retryable = payload["sequence"] > expected_sequence
                return self._conflict_response(
                    payload,
                    error="sequence_gap" if retryable else "stale_sequence",
                    retryable=retryable,
                    detail=(
                        "one or more earlier lifecycle events are not recorded"
                        if retryable
                        else "the call has already advanced beyond this sequence"
                    ),
                    expected_sequence=expected_sequence,
                    current_sequence=call.sequence if call else 0,
                )

        number = (
            payload.get("destination_number")
            if payload["direction"] == "outbound"
            else payload.get("caller_number")
        )
        match = (
            Call.match_customer(
                number,
                payload["campaign_id"],
                business_unit_id=business_unit.id,
            )
            if number and not call
            else {"normalized_number": False, "match": "none", "matches": []}
        )
        exact = match["match"] == "exact"
        lead_match = next(
            (row for row in match["matches"] if exact and row["model"] == "lead"),
            None,
        )
        partner_match = next(
            (row for row in match["matches"] if exact and row["model"] == "partner"),
            None,
        )
        try:
            with request.env.cr.savepoint():
                if not call:
                    call = Call.create(
                        {
                            "name": f"{payload['event_type']} {payload['call_id']}",
                            "call_id": payload["call_id"],
                            "correlation_id": payload["correlation_id"],
                            "asterisk_uniqueid": payload["asterisk_uniqueid"],
                            "uniqueid": payload["asterisk_uniqueid"],
                            "linkedid": payload["linkedid"],
                            "tenant_id": payload["tenant_id"],
                            "keycloak_subject": payload["keycloak_subject"],
                            "business_unit_id": business_unit.code,
                            "campaign_id": campaign.id,
                            "campaign_code": payload["campaign_id"],
                            "agent_id": agent.id,
                            "vicidial_user": agent.vicidial_user,
                            "extension": payload["extension"],
                            "direction": payload["direction"],
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
                            "idempotency_key": "call:" + payload["call_id"],
                        }
                    )
                result = call.apply_authoritative_event(
                    {
                        **payload,
                        "state": self.CALL_EVENTS[payload["event_type"]],
                        "source": "middleware",
                    },
                    strict_sequence=True,
                )
        except ValidationError as exc:
            return self._conflict_response(
                payload,
                error="lifecycle_conflict",
                retryable=False,
                detail=str(exc),
                current_sequence=call.sequence if call else 0,
            )
        evidence = self._evidence(payload, result)
        return request.make_json_response(
            evidence,
            status=200 if result.get("duplicate") else 202,
        )

    @http.route(STATUS_PATH, type="http", auth="none", methods=["GET"], csrf=False)
    def status(self, event_id):
        auth = self._authenticate(b"")
        if auth["event_id"] != event_id:
            raise Forbidden("event identity mismatch")
        event = request.env["codestra.vicidial.call.event"].sudo().search(
            [("idempotency_key", "=", event_id)], limit=1
        )
        if not event:
            raise NotFound("call event not found")
        if (
            event.call_id.tenant_id != auth["tenant_id"]
            or event.correlation_id != auth["correlation_id"]
        ):
            raise Forbidden("call-event read-back scope mismatch")
        return request.make_json_response(
            {
                "event_id": event.idempotency_key,
                "tenant_id": event.call_id.tenant_id,
                "call_id": event.call_id.call_id,
                "event_type": event.event_type,
                "sequence": event.sequence,
                "recorded": True,
            }
        )
