import hashlib
import hmac
import re
import time

MAPPING_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

REQUIRED_HEADERS = (
    "X-Service-Identity",
    "X-Service-Audience",
    "X-Codestra-Timestamp",
    "X-Codestra-Nonce",
    "X-Codestra-Content-SHA256",
    "X-Codestra-Signature",
    "Idempotency-Key",
    "X-Codestra-Environment",
)


def content_sha256(body):
    return hashlib.sha256(body).hexdigest()


def signing_material(
    timestamp,
    nonce,
    method,
    path,
    idempotency_key,
    body_hash,
):
    return "\n".join(  # noqa: FLY002 - canonical ordered signing fields
        (
            method.upper(),
            path,
            timestamp,
            nonce,
            idempotency_key,
            body_hash,
        )
    ).encode()


def signature(secret, **values):
    return hmac.new(
        secret.encode(), signing_material(**values), hashlib.sha256
    ).hexdigest()


def validate_call_mapping(
    campaign_key, agent_key, resolved_campaign_key, resolved_agent_key
):
    if (
        not isinstance(campaign_key, str)
        or not MAPPING_KEY_RE.fullmatch(campaign_key)
        or not isinstance(agent_key, str)
        or not MAPPING_KEY_RE.fullmatch(agent_key)
    ):
        raise ValueError("Campaign or agent key schema mismatch.")
    if not resolved_campaign_key or campaign_key != resolved_campaign_key:
        raise ValueError("Campaign mapping mismatch.")
    if not resolved_agent_key or agent_key != resolved_agent_key:
        raise ValueError("Agent mapping mismatch.")


def validate_request(
    headers,
    body,
    method,
    path,
    secret,
    expected_identity,
    expected_audience,
    expected_environment,
    now=None,
    max_age_seconds=300,
):
    missing = [name for name in REQUIRED_HEADERS if not headers.get(name)]
    if missing:
        raise ValueError("Missing required service authentication header.")
    timestamp = headers["X-Codestra-Timestamp"]
    try:
        fresh = abs((time.time() if now is None else now) - int(timestamp))
        if fresh > max_age_seconds:
            raise ValueError("Expired service authentication timestamp.")
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid service authentication timestamp.") from exc
    if headers["X-Service-Identity"] != expected_identity:
        raise ValueError("Wrong service identity.")
    if headers["X-Service-Audience"] != expected_audience:
        raise ValueError("Wrong service audience.")
    if headers["X-Codestra-Environment"] != expected_environment:
        raise ValueError("Wrong service environment.")
    actual_hash = content_sha256(body)
    if not hmac.compare_digest(actual_hash, headers["X-Codestra-Content-SHA256"]):
        raise ValueError("Request body hash mismatch.")
    expected_signature = signature(
        secret,
        timestamp=timestamp,
        nonce=headers["X-Codestra-Nonce"],
        method=method,
        path=path,
        idempotency_key=headers["Idempotency-Key"],
        body_hash=actual_hash,
    )
    if not secret or not hmac.compare_digest(
        expected_signature, headers["X-Codestra-Signature"]
    ):
        raise ValueError("Invalid service authentication signature.")
    if len(headers["Idempotency-Key"]) < 16:
        raise ValueError("Invalid idempotency key.")
    if len(headers["X-Codestra-Nonce"]) < 16:
        raise ValueError("Invalid service authentication nonce.")
    return {
        "environment": headers["X-Codestra-Environment"],
        "idempotency_key": headers["Idempotency-Key"],
        "identity": headers["X-Service-Identity"],
        "nonce": headers["X-Codestra-Nonce"],
        "timestamp": timestamp,
    }
