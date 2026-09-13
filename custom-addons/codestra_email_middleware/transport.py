"""Credential-file transport for canonical Middleware transactional email."""

import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from uuid import UUID

MAX_RESPONSE = 256 * 1024
MESSAGE_STATES = {
    "accepted": "accepted",
    "queued": "queued",
    "dispatched": "provider_accepted",
    "delivered": "delivered",
    "indeterminate": "deferred",
    "suppressed": "suppressed",
    "failed": "failed",
    "cancelled": "failed",
    "expired": "failed",
}
EVENT_STATES = {
    "accepted": "accepted",
    "queued": "queued",
    "submitted": "provider_accepted",
    "sent": "provider_accepted",
    "delivered": "delivered",
    "deferred": "deferred",
    "bounced": "bounced",
    "complained": "complained",
    "unsubscribed": "suppressed",
    "suppressed": "suppressed",
    "rejected": "rejected",
    "failed": "failed",
    "cancelled": "failed",
    "unknown_outcome": "failed",
}
STATE_RANK = {
    "requested": 0,
    "accepted": 1,
    "queued": 2,
    "provider_accepted": 3,
    "deferred": 4,
    "failed": 5,
    "rejected": 6,
    "bounced": 7,
    "delivered": 8,
    "complained": 9,
    "suppressed": 10,
}
TERMINAL = {
    "delivered", "bounced", "complained", "suppressed", "rejected", "failed",
}


class EmailTransportError(Exception):
    """The exception contains a fixed code, never response or secret content."""

    @property
    def retryable(self):
        code = str(self)
        return code in {"HTTP_429", "TRANSPORT_OR_RESPONSE_ERROR"} or bool(
            re.fullmatch(r"HTTP_5[0-9]{2}", code)
        )


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise EmailTransportError("REDIRECT_REFUSED")


def enabled():
    return os.getenv("CODESTRA_EMAIL_ENABLED", "false").lower() == "true"


def delivery_enabled():
    return enabled() and os.getenv("ALLOW_LIVE_EMAIL", "false").lower() == "true"


def configuration(environ=None):
    source = os.environ if environ is None else environ
    names = (
        "API_BASE_URL", "TOKEN_URL", "CLIENT_SECRET_FILE", "CA_FILE",
        "TENANT_ID", "COMPANY_ID", "SENDER",
    )
    config = {
        name.lower(): source.get("CODESTRA_EMAIL_" + name, "").strip()
        for name in names
    }
    if not all(config.values()):
        raise EmailTransportError("CONFIGURATION_MISSING")
    for name in ("api_base_url", "token_url"):
        value = config[name]
        try:
            parts = urllib.parse.urlsplit(value)
            valid = (
                parts.scheme == "https" and parts.hostname and parts.port != 0
                and not parts.username and not parts.password
                and not parts.query and not parts.fragment
                and not any(ord(char) <= 32 for char in value)
            )
        except ValueError:
            valid = False
        if not valid:
            raise EmailTransportError("HTTPS_CONFIGURATION_REQUIRED")
    api = urllib.parse.urlsplit(config["api_base_url"])
    if api.path not in ("", "/"):
        raise EmailTransportError("API_ORIGIN_REQUIRED")
    config["api_base_url"] = config["api_base_url"].rstrip("/")
    for name in ("client_secret_file", "ca_file"):
        if not os.path.isabs(config[name]):
            raise EmailTransportError("ABSOLUTE_SECRET_PATH_REQUIRED")
    if not config["company_id"].isdigit() or int(config["company_id"]) < 1:
        raise EmailTransportError("COMPANY_CONFIGURATION_INVALID")
    config["company_id"] = int(config["company_id"])
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", config["tenant_id"]):
        raise EmailTransportError("TENANT_CONFIGURATION_INVALID")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+", config["sender"]):
        raise EmailTransportError("SENDER_CONFIGURATION_INVALID")
    config["sender"] = config["sender"].lower()
    return config


def validate_message(result, *, tenant, key, correlation, mail_id, message_id=None):
    if not isinstance(result, dict):
        raise EmailTransportError("INVALID_ACKNOWLEDGEMENT")
    metadata = result.get("metadata")
    if (
        result.get("tenantId") != tenant
        or result.get("idempotencyKey") != key
        or result.get("correlationId") != correlation
        or result.get("channel") != "email"
        or result.get("direction") != "outbound"
        or result.get("status") not in MESSAGE_STATES
        or not isinstance(metadata, dict)
        or str(metadata.get("odooMailId")) != str(mail_id)
    ):
        raise EmailTransportError("ACKNOWLEDGEMENT_IDENTITY_MISMATCH")
    try:
        identity = str(UUID(result["messageId"]))
    except (KeyError, ValueError, TypeError, AttributeError):
        raise EmailTransportError("INVALID_MESSAGE_ID") from None
    if message_id and identity != message_id:
        raise EmailTransportError("ACKNOWLEDGEMENT_IDENTITY_MISMATCH")
    return MESSAGE_STATES[result["status"]], identity, result.get("providerReference")


def state_from_events(result, fallback):
    if not isinstance(result, dict) or not isinstance(result.get("items"), list):
        raise EmailTransportError("INVALID_EVENT_TIMELINE")
    state = fallback
    for event in result["items"]:
        if not isinstance(event, dict):
            raise EmailTransportError("INVALID_EVENT_TIMELINE")
        event_type = str(event.get("type") or "").rsplit(".", 1)[-1]
        candidate = EVENT_STATES.get(event_type)
        if candidate and STATE_RANK[candidate] > STATE_RANK[state]:
            state = candidate
    return state


class MiddlewareEmailClient:
    def __init__(self, config):
        self.config = config
        try:
            context = ssl.create_default_context(cafile=config["ca_file"])
        except (OSError, ssl.SSLError):
            raise EmailTransportError("CA_UNAVAILABLE") from None
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect(),
            urllib.request.HTTPSHandler(context=context),
        )

    def _request(self, request):
        try:
            with self.opener.open(request, timeout=15) as response:  # nosec B310
                if response.status not in (200, 202):
                    raise EmailTransportError("UNEXPECTED_HTTP_STATUS")
                raw = response.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise EmailTransportError("RESPONSE_TOO_LARGE")
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise EmailTransportError("INVALID_JSON_OBJECT")
                return value
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            raise EmailTransportError("HTTP_%s" % code) from None
        except (OSError, urllib.error.URLError, ValueError):
            raise EmailTransportError("TRANSPORT_OR_RESPONSE_ERROR") from None

    def token(self):
        try:
            with open(self.config["client_secret_file"], encoding="utf-8") as handle:
                secret = handle.read(8193).strip()
        except OSError:
            raise EmailTransportError("CREDENTIAL_UNAVAILABLE") from None
        if not secret or len(secret) > 8192:
            raise EmailTransportError("CREDENTIAL_INVALID")
        body = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": "odoo-email",
            "client_secret": secret,
        }).encode()
        value = self._request(urllib.request.Request(
            self.config["token_url"], data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ))
        token = value.get("access_token")
        if (
            not isinstance(token, str) or not token or len(token) > 16384
            or any(ord(char) <= 32 for char in token)
        ):
            raise EmailTransportError("INVALID_TOKEN_RESPONSE")
        return token

    def message(self, *, token, tenant, key, correlation, payload=None):
        headers = {
            "Authorization": "Bearer " + token,
            "X-Tenant-ID": tenant,
            "Idempotency-Key": key,
            "X-Correlation-ID": correlation,
            "Accept": "application/json",
        }
        path = "/v1/communications/messages"
        body = None
        method = "GET"
        if payload is None:
            path += "/by-idempotency"
        else:
            method = "POST"
            body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
            headers["Content-Type"] = "application/json"
        return self._request(urllib.request.Request(
            self.config["api_base_url"] + path,
            data=body, method=method, headers=headers,
        ))

    def events(self, *, token, tenant, key, correlation, message_id):
        headers = {
            "Authorization": "Bearer " + token,
            "X-Tenant-ID": tenant,
            "Idempotency-Key": key,
            "X-Correlation-ID": correlation,
            "Accept": "application/json",
        }
        return self._request(urllib.request.Request(
            self.config["api_base_url"]
            + "/v1/communications/messages/" + message_id + "/events",
            method="GET", headers=headers,
        ))
