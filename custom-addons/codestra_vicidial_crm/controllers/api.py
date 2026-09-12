import hashlib
import hmac
import json
import time
from datetime import datetime, timezone

from odoo import http, release
from odoo.exceptions import ValidationError
from odoo.http import request
from werkzeug.exceptions import BadRequest, Conflict, Forbidden, Gone, NotFound


class CodestraAPI(http.Controller):
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
        # Deprecated and confirmed unreferenced (2026-09-12): no live caller
        # anywhere in this org uses this path. The real, actively-dispatched
        # contract is Middleware's app/vicidial_odoo_projection_models.py,
        # which POSTs to /codestra/middleware/v1/call-events
        # (custom-addons/codestra_vicidial_crm/controllers/
        # call_event_projection.py). That path also has strictly stronger
        # guarantees this duplicate lacked: business-unit scoping, strict
        # sequence-gap conflict detection, atomic savepoints, idempotency-key
        # event dedup, and method/path-bound HMAC signing. Kept as an explicit
        # Gone response, not a bare 404, so any caller still pointed here by
        # stale documentation gets a clear signal instead of silent failure.
        raise Gone(
            "/codestra/api/v1/call-events is retired. Use "
            "/codestra/middleware/v1/call-events instead."
        )

    @http.route("/codestra/api/v1/sync/preview", type="jsonrpc", auth="user", methods=["POST"], csrf=False)
    def preview(self):
        return {"read_only": True, "changes": []}
