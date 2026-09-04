import hashlib
import hmac
import time

from odoo import http
from odoo.http import request
from werkzeug.exceptions import BadRequest, Forbidden, NotFound


class CodestraVicidialCallReadback(http.Controller):
    @staticmethod
    def signature(secret, timestamp, body):
        return hmac.new(
            secret.encode(),
            timestamp.encode() + b"." + body,
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def timestamp_is_fresh(timestamp, now=None, tolerance=300):
        try:
            return abs((time.time() if now is None else now) - int(timestamp)) <= tolerance
        except (TypeError, ValueError):
            return False

    def _verify(self):
        timestamp = request.httprequest.headers.get("X-Codestra-Timestamp")
        signature = request.httprequest.headers.get("X-Codestra-Signature")
        event_id = request.httprequest.headers.get("X-Codestra-Event-ID")
        tenant_id = request.httprequest.headers.get("X-Codestra-Tenant-ID")
        if not timestamp or not signature or not event_id or not tenant_id:
            raise Forbidden("Missing call-event read-back identity headers")
        if not self.timestamp_is_fresh(timestamp):
            raise Forbidden("Expired timestamp")
        if len(event_id) > 128 or len(tenant_id) > 128:
            raise Forbidden("Read-back identity header exceeds the size limit")
        body = request.httprequest.get_data()
        if body:
            raise BadRequest(
                "call-event read-back does not accept a request body"
            )
        secret = (
            request.env["ir.config_parameter"]
            .sudo()
            .get_param("codestra.webhook_secret")
        )
        expected = self.signature(secret or "", timestamp, body)
        if not secret or not hmac.compare_digest(expected, signature):
            raise Forbidden("Invalid signature")
        return event_id, tenant_id

    @http.route(
        "/codestra/api/v1/call-events/<string:event_id>",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def call_event_readback(self, event_id):
        header_event_id, tenant_id = self._verify()
        if header_event_id != event_id:
            raise Forbidden("event identity mismatch")
        event = (
            request.env["codestra.vicidial.call.event"]
            .sudo()
            .search([("idempotency_key", "=", event_id)], limit=1)
        )
        if not event:
            raise NotFound("call event not found")
        call = event.call_id
        if not call or call.tenant_id != tenant_id:
            raise Forbidden("tenant rejected")
        response = request.make_json_response(
            {
                "event_id": event.idempotency_key,
                "event_type": event.event_type,
                "call_id": call.call_id,
                "sequence": event.sequence,
                "state": call.state,
                "payload_hash": event.payload_hash,
            }
        )
        response.headers["Cache-Control"] = "no-store"
        return response
