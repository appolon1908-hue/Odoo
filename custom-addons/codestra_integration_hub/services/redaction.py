import re

from odoo.exceptions import ValidationError

from .canonical_json import canonical_json

SENSITIVE_PARTS = (
    "password", "passwd", "pass", "secret", "token", "authorization",
    "cookie", "credential", "private_key", "api_key", "access_key",
    "encryption_key", "client_secret",
)
REDACTED = "[REDACTED]"
MAX_DEPTH = 20
MAX_PAYLOAD_BYTES = 65536
BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+=*")


def _sensitive(key):
    normalized = str(key).lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_PARTS)


def redact(value, depth=0):
    if depth > MAX_DEPTH:
        return "[MAX_DEPTH]"
    if isinstance(value, dict):
        return {
            str(key): REDACTED if _sensitive(key) else redact(item, depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, depth + 1) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item, depth + 1) for item in value)
    if isinstance(value, str):
        return BEARER_RE.sub("Bearer [REDACTED]", value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def redact_and_validate(value):
    redacted = redact(value)
    encoded = canonical_json(redacted).encode("utf-8")
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise ValidationError("Redacted payload exceeds the 65536-byte storage limit.")
    return redacted
