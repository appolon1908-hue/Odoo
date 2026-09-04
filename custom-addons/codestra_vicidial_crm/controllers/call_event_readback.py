import hashlib
import hmac
import re
import time

from odoo import http
from odoo.exceptions import AccessError, ValidationError
from odoo.http import request
from werkzeug.exceptions import BadRequest, Forbidden, NotFound


_IDENTIFIER = re.compile(r"^[A-Za-z0-9._:-]+$")


class CallEventReadbackAPI(http.Controller):
    """Read-only reconciliation surface for Middleware call-event delivery."""

    @staticmethod
    def signature(secret, timestamp, path, event_id, tenant_id, body=b""):
        body_hash = hashlib.sha256(body).hexdigest()
        canonical = "\n".join(
            (
                "v2",
                "GET",
                path,
                str(timestamp),
                event_id,
                tenant_id,
                body_hash,
            )
        ).encode()
        return "sha256=" + hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()

    @staticmethod
    def timestamp_is_fresh(timestamp, now=None, tolerance=300):
        try:
            return abs((time.time() if now is None else now) - int(timestamp)) <= tolerance
        except (TypeError, ValueError):
            return False

    def _verify(self, route_event_id):
        headers = request.httprequest.headers
        timestamp = headers.get("X-Codestra-Timestamp")
        signature = headers.get("X-Codestra-Signature")
        signature_version = headers.get("X-Codestra-Signature-Version")
        event_id = headers.get("X-Codestra-Event-ID")
        tenant_id = headers.get("X-Codestra-Tenant-ID")
        body = request.httprequest.get_data()
        path = request.httprequest.path

        if signature_version != "v2":
            raise Forbidden("Call event readback requires signature version v2")
        if not timestamp or not signature or not event_id or not tenant_id:
            raise Forbidden("Missing call event readback signature headers")
        if not self.timestamp_is_fresh(timestamp):
            raise Forbidden("Expired call event readback timestamp")
        if body:
            raise BadRequest("Call event readback requests must not contain a body")
        if (
            route_event_id != event_id
            or len(event_id) > 255
            or not _IDENTIFIER.fullmatch(event_id)
        ):
            raise Forbidden("Call event readback identity mismatch")
        if len(tenant_id) > 128 or not _IDENTIFIER.fullmatch(tenant_id):
            raise Forbidden("Invalid call event readback tenant")

        expected_path = "/codestra/api/v1/call-events/" + event_id
        if path != expected_path:
            raise Forbidden("Call event readback path mismatch")

        secret = (
            request.env["ir.config_parameter"]
            .sudo()
            .get_param("codestra.webhook_secret")
        )
        if not secret or len(secret.encode()) < 32:
            raise Forbidden("Call event readback secret is unavailable")
        expected = self.signature(
            secret,
            timestamp,
            expected_path,
            event_id,
            tenant_id,
            body,
        )
        if not hmac.compare_digest(expected, signature):
            raise Forbidden("Invalid call event readback signature")
        return tenant_id

    @http.route(
        "/codestra/api/v1/call-events/<string:event_id>",
        type="http",
        auth="none",
        methods=["GET"],
        csrf=False,
    )
    def call_event_readback(self, event_id):
        tenant_id = self._verify(event_id)
        try:
            evidence = request.env[
                "codestra.vicidial.call.event"
            ].codestra_readback(event_id, tenant_id)
        except AccessError as exc:
            raise Forbidden(str(exc)) from exc
        except ValidationError as exc:
            raise BadRequest(str(exc)) from exc
        if not evidence:
            raise NotFound("Call event evidence not found")
        response = request.make_json_response(evidence)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
