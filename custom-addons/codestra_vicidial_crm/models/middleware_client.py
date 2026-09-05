import json
import socket
import urllib.error
import urllib.parse
import urllib.request

from odoo import api, models
from odoo.exceptions import UserError


class TelephonyMiddlewareClient(models.AbstractModel):
    _name = "codestra.telephony.middleware.client"
    _description = "Governed Codestra Telephony Middleware Client"

    @api.model
    def _validated_target(self, value):
        parsed = urllib.parse.urlsplit(value or "")
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path != "/v1/telephony/calls/originate"
        ):
            raise UserError(
                "Click-to-call middleware must use a credential-free HTTPS endpoint."
            )
        return value

    @api.model
    def originate_call(self, correlation_id, idempotency_key, payload):
        params = self.env["ir.config_parameter"].sudo()
        target = params.get_param("codestra.middleware.telephony_originate_url")
        api_key = params.get_param("codestra.middleware.api_key")
        if not target or not api_key:
            raise UserError("Click-to-call middleware is not configured.")
        target = self._validated_target(target)
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
                "Idempotency-Key": idempotency_key,
            },
            method="POST",
        )
        try:
            # _validated_target rejects non-HTTPS and credential-bearing authorities.
            with urllib.request.urlopen(  # nosec B310
                outbound_request, timeout=10
            ) as response:
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
        except (TimeoutError, socket.timeout) as exc:
            return {
                "dialing": "unknown",
                "reason": "timeout; reconcile this request before retrying",
                "retry_safe": False,
            }
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                return {
                    "dialing": "unknown",
                    "reason": "timeout; reconcile this request before retrying",
                    "retry_safe": False,
                }
            raise UserError(
                "The telephony service is unavailable. Try again shortly."
            ) from exc
        if not isinstance(result, dict) or "dialing" not in result:
            raise UserError("The telephony service returned an invalid response.")
        return result
