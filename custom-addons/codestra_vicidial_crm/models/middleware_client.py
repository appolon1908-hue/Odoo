import json
import urllib.error
import urllib.request

from odoo import api, models
from odoo.exceptions import UserError


class TelephonyMiddlewareClient(models.AbstractModel):
    _name = "codestra.telephony.middleware.client"
    _description = "Governed Codestra Telephony Middleware Client"

    @api.model
    def originate_call(self, correlation_id, idempotency_key, payload):
        params = self.env["ir.config_parameter"].sudo()
        target = params.get_param("codestra.middleware.telephony_originate_url")
        api_key = params.get_param("codestra.middleware.api_key")
        if not target or not api_key:
            raise UserError("Click-to-call middleware is not configured.")
        raw = json.dumps(
            dict(payload, idempotency_key=idempotency_key), separators=(",", ":")
        ).encode()
        outbound_request = urllib.request.Request(
            target,
            raw,
            {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + api_key,
                "X-Correlation-ID": correlation_id,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(outbound_request, timeout=10) as response:
                result = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read()).get("detail")
            except (AttributeError, ValueError):
                detail = None
            messages = {
                403: "You are not authorized to call from this campaign.",
                422: "This phone number could not be validated.",
                429: "Too many call attempts; wait a moment and try again.",
            }
            raise UserError(
                detail or messages.get(exc.code, "Call could not be started.")
            ) from exc
        except urllib.error.URLError as exc:
            raise UserError(
                "The telephony service is unavailable. Try again shortly."
            ) from exc
        if not isinstance(result, dict) or "dialing" not in result:
            raise UserError("The telephony service returned an invalid response.")
        return result
