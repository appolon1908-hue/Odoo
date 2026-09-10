"""Credential-file transport for the canonical Middleware communications API."""

import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from uuid import UUID

MAX_RESPONSE = 256 * 1024
STATES = {
    "accepted": ("process", "QUEUED"),
    "queued": ("process", "QUEUED"),
    "dispatched": ("pending", "SUBMITTED"),
    "delivered": ("sent", "DELIVERED"),
    "failed": ("error", "FAILED"),
    "cancelled": ("canceled", "FAILED"),
    "suppressed": ("error", "OPTED_OUT"),
    "expired": ("error", "FAILED"),
    "indeterminate": ("process", "SUBMITTED"),
}
TERMINAL = {"delivered", "failed", "cancelled", "suppressed", "expired"}


class SmsTransportError(Exception):
    """The exception contains only a fixed error code, never response content."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SmsTransportError("REDIRECT_REFUSED")


def enabled():
    return os.getenv("CODESTRA_SMS_ENABLED", "false").lower() == "true"


def delivery_enabled():
    return enabled() and os.getenv("ALLOW_LIVE_SMS", "false").lower() == "true"


def configuration(environ=None):
    source = os.environ if environ is None else environ
    names = ("API_BASE_URL", "TOKEN_URL", "CLIENT_SECRET_FILE", "CA_FILE",
             "TENANT_ID", "COMPANY_ID", "BUSINESS_UNIT_ID", "SENDER", "BILLING_ACCOUNT_ID")
    config = {name.lower(): source.get("CODESTRA_SMS_" + name, "").strip() for name in names}
    if not all(config.values()):
        raise SmsTransportError("CONFIGURATION_MISSING")
    for name in ("api_base_url", "token_url"):
        value = config[name]
        try:
            parts = urllib.parse.urlsplit(value)
            valid = (parts.scheme == "https" and parts.hostname and parts.port != 0
                     and not parts.username and not parts.password
                     and not parts.query and not parts.fragment
                     and not any(ord(char) <= 32 for char in value))
        except ValueError:
            valid = False
        if not valid:
            raise SmsTransportError("HTTPS_CONFIGURATION_REQUIRED")
    api = urllib.parse.urlsplit(config["api_base_url"])
    if api.path not in ("", "/"):
        raise SmsTransportError("API_ORIGIN_REQUIRED")
    config["api_base_url"] = config["api_base_url"].rstrip("/")
    for name in ("client_secret_file", "ca_file"):
        if not os.path.isabs(config[name]):
            raise SmsTransportError("ABSOLUTE_SECRET_PATH_REQUIRED")
    for name in ("company_id", "business_unit_id"):
        if not config[name].isdigit() or int(config[name]) < 1:
            raise SmsTransportError("SCOPE_CONFIGURATION_INVALID")
        config[name] = int(config[name])
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", config["tenant_id"]):
        raise SmsTransportError("TENANT_CONFIGURATION_INVALID")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,36}", config["billing_account_id"]):
        raise SmsTransportError("BILLING_CONFIGURATION_INVALID")
    if not re.fullmatch(r"(?:\+[1-9][0-9]{5,14}|[A-Za-z0-9][A-Za-z0-9 ._-]{0,19})", config["sender"]):
        raise SmsTransportError("SENDER_CONFIGURATION_INVALID")
    return config


def validate_message(result, *, tenant, key, correlation, sms_uuid, message_id=None):
    if not isinstance(result, dict):
        raise SmsTransportError("INVALID_ACKNOWLEDGEMENT")
    metadata = result.get("metadata")
    if (result.get("tenantId") != tenant or result.get("idempotencyKey") != key
            or result.get("correlationId") != correlation or result.get("channel") != "sms"
            or result.get("direction") != "outbound" or result.get("status") not in STATES
            or not isinstance(metadata, dict) or metadata.get("odooSmsUuid") != sms_uuid):
        raise SmsTransportError("ACKNOWLEDGEMENT_IDENTITY_MISMATCH")
    try:
        identity = str(UUID(result["messageId"]))
    except (KeyError, ValueError, TypeError, AttributeError):
        raise SmsTransportError("INVALID_MESSAGE_ID") from None
    if message_id and identity != message_id:
        raise SmsTransportError("ACKNOWLEDGEMENT_IDENTITY_MISMATCH")
    return result["status"], identity


class MiddlewareSmsClient:
    def __init__(self, config):
        self.config = config
        try:
            context = ssl.create_default_context(cafile=config["ca_file"])
        except (OSError, ssl.SSLError):
            raise SmsTransportError("CA_UNAVAILABLE") from None
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect(),
            urllib.request.HTTPSHandler(context=context),
        )

    def _request(self, request):
        try:
            with self.opener.open(request, timeout=15) as response:  # nosec B310: validated HTTPS, no redirects/proxies
                if response.status not in (200, 202):
                    raise SmsTransportError("UNEXPECTED_HTTP_STATUS")
                raw = response.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise SmsTransportError("RESPONSE_TOO_LARGE")
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise SmsTransportError("INVALID_JSON_OBJECT")
                return value
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            raise SmsTransportError("HTTP_%s" % code) from None
        except (OSError, urllib.error.URLError, ValueError):
            raise SmsTransportError("TRANSPORT_OR_RESPONSE_ERROR") from None

    def token(self, *, write=False):
        try:
            with open(self.config["client_secret_file"], encoding="utf-8") as handle:
                secret = handle.read(8193).strip()
        except OSError:
            raise SmsTransportError("CREDENTIAL_UNAVAILABLE") from None
        if not secret or len(secret) > 8192:
            raise SmsTransportError("CREDENTIAL_INVALID")
        body = urllib.parse.urlencode({
            "grant_type": "client_credentials", "client_id": "odoo-sms",
            "client_secret": secret,
            "scope": "odoo.sms.command.write" if write else "odoo.sms.status.read",
        }).encode()
        value = self._request(urllib.request.Request(
            self.config["token_url"], data=body, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ))
        token = value.get("access_token")
        if (not isinstance(token, str) or not token or len(token) > 16384
                or any(ord(char) <= 32 for char in token)):
            raise SmsTransportError("INVALID_TOKEN_RESPONSE")
        return token

    def message(self, *, token, tenant, key, correlation, payload=None):
        headers = {"Authorization": "Bearer " + token, "X-Tenant-ID": tenant,
                   "Idempotency-Key": key, "X-Correlation-ID": correlation,
                   "Accept": "application/json"}
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
            self.config["api_base_url"] + path, data=body, method=method, headers=headers,
        ))
