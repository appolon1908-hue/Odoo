from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone

IDENTITY = "codestra-middleware"
AUDIENCE = "codestra-odoo-lead-automation-api"
SIGNATURE_VERSION = "HMAC-V2"
SCOPE = "lead-automation.odoo-apply.write"
HTTP_METHOD = "POST"
REQUEST_PATH = "/codestra/api/v1/leads/automation/apply"
HEADERS = (
    "X-Codestra-Signature-Version",
    "X-Service-Identity",
    "X-Service-Audience",
    "X-Codestra-Timestamp",
    "X-Codestra-Nonce",
    "X-Codestra-Content-SHA256",
    "X-Codestra-Signature",
    "Idempotency-Key",
    "X-Codestra-Environment",
    "X-Codestra-Scope",
)


class AuthenticationError(PermissionError):
    pass


def signing_material(
    signature_version: str,
    method: str,
    path: str,
    timestamp: str,
    nonce: str,
    service_identity: str,
    service_audience: str,
    environment: str,
    scope: str,
    idempotency_key: str,
    body_hash: str,
) -> bytes:
    values = (
        signature_version,
        method,
        path,
        timestamp,
        nonce,
        service_identity,
        service_audience,
        environment,
        scope,
        idempotency_key,
        body_hash,
    )
    if any(not value or "\n" in value or "\r" in value for value in values):
        raise AuthenticationError("invalid signing material")
    return "\n".join(values).encode("ascii")


def verify(
    *,
    method: str,
    path: str,
    query_string: bytes,
    body: bytes,
    headers: dict[str, str],
    secret: bytes,
    expected_environment: str,
    used_nonces: set[tuple[str, str, str, str]],
    now: datetime | None = None,
) -> str:
    if any(not headers.get(name) for name in HEADERS) or not secret:
        raise AuthenticationError("missing signature material")
    if not hmac.compare_digest(method, HTTP_METHOD) or not hmac.compare_digest(
        path, REQUEST_PATH
    ):
        raise AuthenticationError("wrong method or path")
    if query_string:
        raise AuthenticationError("query string is prohibited")
    for supplied, expected, message in (
        (
            headers["X-Codestra-Signature-Version"],
            SIGNATURE_VERSION,
            "unsupported signature version",
        ),
        (headers["X-Service-Identity"], IDENTITY, "wrong service identity"),
        (headers["X-Service-Audience"], AUDIENCE, "wrong audience"),
        (
            headers["X-Codestra-Environment"],
            expected_environment,
            "wrong environment",
        ),
        (headers["X-Codestra-Scope"], SCOPE, "wrong scope"),
    ):
        if not hmac.compare_digest(supplied, expected):
            raise AuthenticationError(message)
    body_hash = hashlib.sha256(body).hexdigest()
    if not hmac.compare_digest(body_hash, headers["X-Codestra-Content-SHA256"]):
        raise AuthenticationError("body hash mismatch")
    try:
        occurred = datetime.fromisoformat(headers["X-Codestra-Timestamp"])
    except ValueError as exc:
        raise AuthenticationError("invalid timestamp") from exc
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if occurred.tzinfo is None or abs((current - occurred.astimezone(timezone.utc)).total_seconds()) > 300:
        raise AuthenticationError("expired timestamp")
    expected_signature = hmac.new(
        secret,
        signing_material(
            headers["X-Codestra-Signature-Version"],
            method,
            path,
            headers["X-Codestra-Timestamp"],
            headers["X-Codestra-Nonce"],
            headers["X-Service-Identity"],
            headers["X-Service-Audience"],
            headers["X-Codestra-Environment"],
            headers["X-Codestra-Scope"],
            headers["Idempotency-Key"],
            body_hash,
        ),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, headers["X-Codestra-Signature"]):
        raise AuthenticationError("invalid signature")
    nonce_key = (
        expected_environment,
        SCOPE,
        path,
        headers["X-Codestra-Nonce"],
    )
    if nonce_key in used_nonces:
        raise AuthenticationError("reused nonce")
    used_nonces.add(nonce_key)
    return headers["Idempotency-Key"]
