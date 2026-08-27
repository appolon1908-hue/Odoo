import hashlib
import hmac
import json
import os
import time
from pathlib import Path

from odoo import http
from odoo.http import request


def _callback_key():
    reference = os.getenv("ODOO_CALLBACK_HMAC_SECRET_FILE")
    if not reference:
        return None
    path = Path(reference)
    try:
        mode = path.stat().st_mode
        if path.is_symlink() or not path.is_file() or mode & 0o027:
            return None
        return path.read_text().strip() or None
    except OSError:
        return None


class ProvisioningCallbackController(http.Controller):
    @http.route(
        "/codestra/provisioning/v1/callback",
        type="http", auth="none", methods=["POST"], csrf=False, save_session=False,
    )
    def provisioning_callback(self):
        timestamp = request.httprequest.headers.get("X-Codestra-Timestamp", "")
        signature = request.httprequest.headers.get("X-Codestra-Signature", "")
        secret = _callback_key()
        try:
            issued_at = int(timestamp)
        except (TypeError, ValueError):
            issued_at = 0
        raw = request.httprequest.get_data(cache=False)
        expected = hmac.new(
            (secret or "").encode(), timestamp.encode() + b"." + raw, hashlib.sha256
        ).hexdigest()
        if (
            not secret or abs(int(time.time()) - issued_at) > 300
            or not hmac.compare_digest(signature, "sha256=" + expected)
        ):
            return request.make_json_response({"error": "invalid_callback"},
                                              status=401)
        try:
            payload = json.loads(raw)
            result = request.env["codestra.provisioning.request"].sudo(
            ).apply_service_callback(payload)
        except (ValueError, TypeError, KeyError):
            return request.make_json_response({"error": "invalid_payload"},
                                              status=422)
        return request.make_json_response(result, status=200)
