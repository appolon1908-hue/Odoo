import json
import math
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

from odoo import api, models
from odoo.exceptions import UserError


_MAX_MESSAGE_BYTES = 131072

# Canonical calling-contract surface. The legacy origination route below is kept
# until Middleware lead resolution is confirmed equivalent to the destination the
# Odoo payload selects today; see config/calling-contract-usage.json.
_COMMAND_PATH = "/v1/telephony/commands"
_COMMAND_ORIGINATE = "telephony.call.originate.v1"
_COMMAND_SCHEMA_VERSION = 1

# NatsSubjectToken: one subject token, no dots, wildcards, whitespace or slashes.
_NATS_TOKEN = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_UUID = re.compile(
    r"\A[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z", re.IGNORECASE
)
_RFC3339 = re.compile(
    r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})\Z"
)

# Operation.state, split by what each state proves about external effect. Never
# report "blocked" for a state that may have placed a call: a wrong "rejected"
# invites a retry that double-dials.
_OPERATION_ACCEPTED = frozenset(
    {"PERSISTED", "DISPATCH_PENDING", "DISPATCHED", "COMPLETED"}
)
_OPERATION_UNKNOWN = frozenset({"INDETERMINATE", "RECONCILING"})
_OPERATION_TERMINAL = frozenset({"POLICY_DENIED", "CANCELLED", "FAILED"})
_OPERATION_STATES = _OPERATION_ACCEPTED | _OPERATION_UNKNOWN | _OPERATION_TERMINAL


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

    @api.model
    def _validated_command_target(self, value):
        # Same credential-free HTTPS rule as the legacy route, canonical path.
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
                or parsed.path != _COMMAND_PATH
            ):
                raise ValueError("invalid target")
        except (ValueError, TypeError) as exc:
            raise OriginateRejected(
                "Click-to-call middleware must use a credential-free HTTPS endpoint."
            ) from exc
        return value

    @api.model
    def _canonical_command(self, values):
        """Build the closed Command object the calling authority defines.

        The authority marks Command additionalProperties:false, so anything the
        legacy payload carried that has no canonical field -- destination number,
        caller ID, recording flag, destination class/country/timezone -- cannot be
        sent. Middleware resolves the dial target from the lead references
        instead. Reject unknown keys loudly rather than dropping them silently,
        so a caller cannot believe it passed a destination that never left Odoo.
        """
        required_tokens = ("tenant_id", "campaign_id", "agent_id")
        required_plain = ("business_unit_id", "odoo_user_id")
        optional_plain = (
            "odoo_lead_id",
            "vicidial_user_id",
            "vicidial_campaign_id",
            "vicidial_lead_id",
        )
        allowed = set(required_tokens) | set(required_plain) | set(optional_plain) | {
            "operation_id",
            "correlation_id",
            "requested_at",
        }
        if not isinstance(values, dict) or not set(values) <= allowed:
            raise OriginateRejected("Click-to-call command fields are not canonical.")
        if not {*required_tokens, *required_plain, "operation_id", "correlation_id", "requested_at"} <= set(values):
            raise OriginateRejected("Click-to-call command is missing required identity.")

        command = {"type": _COMMAND_ORIGINATE, "schema_version": _COMMAND_SCHEMA_VERSION}
        for field in required_tokens:
            value = values[field]
            if not isinstance(value, str) or not _NATS_TOKEN.match(value):
                raise OriginateRejected(
                    "Click-to-call command identity is not a valid subject token."
                )
            command[field] = value
        for field in required_plain:
            value = values[field]
            if not _visible_ascii(value, 255):
                raise OriginateRejected("Click-to-call command identity is invalid.")
            command[field] = value
        for field in optional_plain:
            if field not in values or values[field] is None:
                continue
            value = values[field]
            if not _visible_ascii(value, 255):
                raise OriginateRejected("Click-to-call command reference is invalid.")
            command[field] = value
        for field in ("operation_id", "correlation_id"):
            value = values[field]
            if not isinstance(value, str) or not _UUID.match(value):
                raise OriginateRejected("Click-to-call command identity must be a UUID.")
            command[field] = value
        requested_at = values["requested_at"]
        if not isinstance(requested_at, str) or not _RFC3339.match(requested_at):
            raise OriginateRejected("Click-to-call command timestamp is invalid.")
        command["requested_at"] = requested_at
        return command

    @api.model
    def _validate_operation_response(self, result, operation_id):
        """Map an Operation to a call outcome without ever understating effect."""
        if (
            not isinstance(result, dict)
            or set(result)
            != {"operation_id", "state", "external_effect", "calls_placed"}
            or result["operation_id"] != operation_id
            or result["state"] not in _OPERATION_STATES
            # bool is an int subclass; a JSON true here would otherwise pass as a
            # count, which the release gates already treat as a forged counter.
            or type(result["external_effect"]) is not bool
            or type(result["calls_placed"]) is not int
            or result["calls_placed"] < 0
        ):
            raise OriginateOutcomeUnknown(
                "Middleware returned an invalid operation with an unknown call outcome; "
                "reconcile this call before retrying."
            )
        state = result["state"]
        effect = result["external_effect"]
        if state in _OPERATION_ACCEPTED:
            dialing = "attempting"
        elif state in _OPERATION_UNKNOWN:
            dialing = "unknown"
        elif state == "POLICY_DENIED" and not effect:
            # The authority guarantees a denied command creates no external effect.
            dialing = "blocked"
        elif effect or result["calls_placed"]:
            # Cancelled or failed after something reached the network: a call may
            # exist, so this must reconcile rather than look safely rejected.
            dialing = "unknown"
        else:
            dialing = "blocked"
        return {
            "dialing": dialing,
            "reason": f"operation {state.lower()}",
            "operation_id": result["operation_id"],
            "operation_state": state,
            "external_effect": effect,
            "calls_placed": result["calls_placed"],
        }

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

    @api.private
    @api.model
    def originate_command(self, correlation_id, idempotency_key, values):
        """Post telephony.call.originate.v1 to the canonical command envelope.

        The transport rules are deliberately identical to originate_call: no
        redirects, bounded request and response, duplicate response members
        rejected, non-finite numbers rejected, and a timeout reported as an
        unknown outcome rather than a safe failure. The legacy method is left
        untouched so this path can be proven against Middleware before the live
        click-to-call default moves.
        """
        params = self.env["ir.config_parameter"].sudo()
        target = params.get_param("codestra.middleware.telephony_command_url")
        api_key = params.get_param("codestra.middleware.api_key")
        if not target or not api_key:
            raise OriginateRejected("Click-to-call middleware is not configured.")
        target = self._validated_command_target(target)
        if (
            not _visible_ascii(correlation_id, 255)
            or not _visible_ascii(idempotency_key, 255)
            or not _visible_ascii(api_key, 8192)
        ):
            raise OriginateRejected("Click-to-call request identity is invalid.")
        command = self._canonical_command(values)
        if command["correlation_id"] != correlation_id:
            raise OriginateRejected("Click-to-call correlation identity is inconsistent.")
        operation_id = command["operation_id"]
        try:
            raw = json.dumps(
                command, separators=(",", ":"), allow_nan=False
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
            opener = urllib.request.build_opener(_NoTelephonyRedirect())
            with opener.open(  # nosec B310
                outbound_request, timeout=10
            ) as response:
                raw_result = response.read(_MAX_MESSAGE_BYTES + 1)
                if len(raw_result) > _MAX_MESSAGE_BYTES:
                    raise ValueError("response exceeds maximum size")
                result = json.loads(
                    raw_result.decode("utf-8"),
                    object_pairs_hook=_unique_object,
                    parse_constant=_reject_constant,
                    parse_float=_finite_float,
                )
        except urllib.error.HTTPError as exc:
            messages = {
                403: "You are not authorized to call from this campaign.",
                422: "This phone number could not be validated.",
                429: "Too many call attempts; wait a moment and try again.",
            }
            if exc.code in messages:
                raise OriginateRejected(messages[exc.code]) from exc
            raise OriginateOutcomeUnknown(
                "Middleware returned an error after receiving the call command; "
                "reconcile its operation ID before retrying."
            ) from exc
        except (TimeoutError, socket.timeout):
            return {
                "dialing": "unknown",
                "reason": "timeout; reconcile this operation before retrying",
                "operation_id": operation_id,
                "operation_state": None,
                "external_effect": None,
                "calls_placed": None,
                "retry_safe": False,
            }
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                return {
                    "dialing": "unknown",
                    "reason": "timeout; reconcile this operation before retrying",
                    "operation_id": operation_id,
                    "operation_state": None,
                    "external_effect": None,
                    "calls_placed": None,
                    "retry_safe": False,
                }
            raise OriginateOutcomeUnknown(
                "The telephony connection failed with an unknown command outcome; "
                "reconcile this call before retrying."
            ) from exc
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise OriginateOutcomeUnknown(
                "Middleware returned an invalid operation with an unknown call outcome; "
                "reconcile this call before retrying."
            ) from exc
        return self._validate_operation_response(result, operation_id)
