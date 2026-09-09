import json
import math
import socket
import urllib.error
import urllib.parse
import urllib.request

from odoo import api, models
from odoo.exceptions import UserError


_MAX_MESSAGE_BYTES = 131072


class OriginateRejected(UserError):
    """The request was rejected before a call could be dispatched."""


class OriginateOutcomeUnknown(UserError):
    """The request may have reached Middleware; reconciliation is required."""


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate response member")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("non-finite response number")


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite response number")
    return result


def _visible_ascii(value, maximum):
    return (
        isinstance(value, str)
        and 0 < len(value) <= maximum
        and all(33 <= ord(char) <= 126 for char in value)
    )


class _NoTelephonyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Even a redirect on the same host can escape the reviewed API route.
        # In particular, never forward the bearer credential to a new origin.
        return None


class TelephonyMiddlewareClient(models.AbstractModel):
    _name = "codestra.telephony.middleware.client"
    _description = "Governed Codestra Telephony Middleware Client"

    @api.model
    def _validated_target(self, value):
        # urlsplit silently removes some control characters. Reject the original
        # value before parsing so validation and the transport see the same URL.
        try:
            if not _visible_ascii(value, 2048) or "?" in value or "#" in value:
                raise ValueError("invalid target")
            parsed = urllib.parse.urlsplit(value)
            port = parsed.port  # Also validates malformed/out-of-range ports.
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or (port is not None and port < 1)
                or parsed.path != "/v1/telephony/calls/originate"
            ):
                raise ValueError("invalid target")
        except (ValueError, TypeError) as exc:
            raise OriginateRejected(
                "Click-to-call middleware must use a credential-free HTTPS endpoint."
            ) from exc
        return value

    @api.model
    def _validate_originate_response(self, result):
        if not isinstance(result, dict):
            raise OriginateOutcomeUnknown(
                "Middleware returned an invalid response with an unknown call outcome; "
                "reconcile this call before retrying."
            )
        dialing = result.get("dialing")
        reason = result.get("reason")
        call_id = result.get("call_id")
        if (
            not isinstance(dialing, str)
            # An unrecognized outcome is not proof that no call was placed.
            # Preserve the reservation and its idempotency key for reconciliation.
            or dialing not in {"attempting", "unknown", "blocked"}
            or (reason is not None and not isinstance(reason, str))
            or (call_id is not None and not _visible_ascii(call_id, 255))
        ):
            raise OriginateOutcomeUnknown(
                "Middleware returned an invalid response with an unknown call outcome; "
                "reconcile this call before retrying."
            )
        return result

    @api.private
    @api.model
    def originate_call(self, correlation_id, idempotency_key, payload):
        # Only the governed post-commit dispatcher may use this Python API.
        # @api.model alone does not prevent arbitrary RPC calls using sudo-read
        # service credentials and a caller-supplied campaign/destination payload.
        params = self.env["ir.config_parameter"].sudo()
        target = params.get_param("codestra.middleware.telephony_originate_url")
        api_key = params.get_param("codestra.middleware.api_key")
        if not target or not api_key:
            raise OriginateRejected("Click-to-call middleware is not configured.")
        target = self._validated_target(target)
        if (
            not _visible_ascii(correlation_id, 255)
            or not _visible_ascii(idempotency_key, 255)
            or not _visible_ascii(api_key, 8192)
            or not isinstance(payload, dict)
            or (
                "idempotency_key" in payload
                and payload["idempotency_key"] != idempotency_key
            )
        ):
            raise OriginateRejected("Click-to-call request identity is invalid.")
        try:
            raw = json.dumps(
                dict(payload, idempotency_key=idempotency_key),
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            if len(raw) > _MAX_MESSAGE_BYTES:
                raise ValueError("request exceeds maximum size")
        except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
            raise OriginateRejected("Click-to-call request payload is invalid.") from exc
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
            # Revalidate the initial target and forbid all redirect hops. Default
            # urllib handling can copy Authorization to an unreviewed origin.
            opener = urllib.request.build_opener(_NoTelephonyRedirect())
            with opener.open(  # nosec B310
                outbound_request, timeout=10
            ) as response:
                raw_result = response.read(_MAX_MESSAGE_BYTES + 1)
                if len(raw_result) > _MAX_MESSAGE_BYTES:
                    raise ValueError("response exceeds maximum size")
                # Never interpret duplicate outcome/identity fields using JSON's
                # last-value-wins rule: an accepted call could appear rejected.
                result = json.loads(
                    raw_result.decode("utf-8"),
                    object_pairs_hook=_unique_object,
                    parse_constant=_reject_constant,
                    parse_float=_finite_float,
                )
                if isinstance(result, dict):
                    for field, expected in (
                        ("correlation_id", correlation_id),
                        ("idempotency_key", idempotency_key),
                    ):
                        if field in result and result[field] != expected:
                            raise ValueError("response identity mismatch")
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
        except (TimeoutError, socket.timeout):
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
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise OriginateOutcomeUnknown(
                "Middleware returned an invalid response with an unknown call outcome; "
                "reconcile this call before retrying."
            ) from exc
        return self._validate_originate_response(result)
