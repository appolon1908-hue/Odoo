import json
import socket
import urllib.error
import urllib.parse
import urllib.request

from odoo import api, models
from odoo.exceptions import UserError


class OriginateRejected(UserError):
    """The request was rejected before a call could be dispatched."""


class OriginateOutcomeUnknown(UserError):
    """The request may have reached Middleware; reconciliation is required."""


def validate_originate_result(result):
    """Malformed acknowledgements never prove that no call was dispatched."""
    if not isinstance(result, dict):
        raise OriginateOutcomeUnknown("Invalid Middleware call acknowledgement.")
    dialing = result.get("dialing")
    reason = result.get("reason")
    call_id = result.get("call_id")
    if (
        not isinstance(dialing, str)
        or dialing not in {"attempting", "unknown", "blocked", "rejected", "disabled", "denied"}
        or (reason is not None and not isinstance(reason, str))
        or (call_id is not None and (
            not isinstance(call_id, str) or not 1 <= len(call_id) <= 255
            or any(not (char.isascii() and (char.isalnum() or char in "._:-")) for char in call_id)
        ))
    ):
        raise OriginateOutcomeUnknown("Invalid Middleware call acknowledgement.")
    return dict(result, reason=" ".join((reason or "Call dispatch result received.").split())[:240])


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
            raise OriginateRejected(
                "Click-to-call middleware must use a credential-free HTTPS endpoint."
            )
        return value

    @api.model
    def originate_call(self, correlation_id, idempotency_key, payload):
        params = self.env["ir.config_parameter"].sudo()
        target = params.get_param("codestra.middleware.telephony_originate_url")
        api_key = params.get_param("codestra.middleware.api_key")
        if not target or not api_key:
            raise OriginateRejected("Click-to-call middleware is not configured.")
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
                encoded_result = response.read(65537)
                if len(encoded_result) > 65536:
                    raise OriginateOutcomeUnknown("Oversized Middleware call acknowledgement.")
                result = json.loads(encoded_result)
        except urllib.error.HTTPError as exc:
            messages = {
                403: "You are not authorized to call from this campaign.",
                422: "This phone number could not be validated.",
                429: "Too many call attempts; wait a moment and try again.",
            }
            if exc.code in messages:
                raise OriginateRejected(messages[exc.code]) from exc
            raise OriginateOutcomeUnknown(
                "Middleware returned an error after receiving the call request; "
                "reconcile its correlation ID before retrying."
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
            raise OriginateOutcomeUnknown(
                "The telephony connection failed with an unknown request outcome; "
                "reconcile this call before retrying."
            ) from exc
        if not isinstance(result, dict) or "dialing" not in result:
            raise OriginateOutcomeUnknown(
                "Middleware returned an invalid response with an unknown call outcome; "
                "reconcile this call before retrying."
            )
        return validate_originate_result(result)
