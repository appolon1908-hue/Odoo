import hashlib
import hmac
import json
import os
import ssl
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from stat import S_ISREG
from urllib import parse, request

from odoo import fields, models
from odoo.exceptions import ValidationError

from .provisioning import ACTIVATION_EMAIL_EVENT, PROVISION_EVENT, _canonical_json


AGENT_EVENT_TYPES = {
    PROVISION_EVENT: "codestra.odoo.agent.provisioning_requested",
    ACTIVATION_EMAIL_EVENT: "codestra.odoo.agent.activation_email_requested",
}
MIDDLEWARE_EVENT_PATH = "/api/v1/odoo/events"
MAX_ACK_BYTES = 65536


def _protected_value(path_value, label, *, binary=False):
    path = Path(path_value or "")
    try:
        stat_result = path.stat()
        if (
            path.is_symlink()
            or not S_ISREG(stat_result.st_mode)
            or stat_result.st_mode & 0o027
        ):
            raise OSError
        value = (
            path.read_bytes().strip()
            if binary
            else path.read_text(encoding="utf-8").strip()
        )
    except (OSError, UnicodeError) as error:
        raise ValidationError(
            f"{label} reference is unavailable or unsafe."
        ) from error
    if not value:
        raise ValidationError(f"{label} reference is empty.")
    return value


def _event_endpoint(value):
    parsed = parse.urlsplit((value or "").strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path != MIDDLEWARE_EVENT_PATH
    ):
        raise ValidationError(
            "The agent-event endpoint must be credential-free HTTPS at "
            f"{MIDDLEWARE_EVENT_PATH}."
        )
    return parsed.geturl()


def _iso_utc(value):
    if not value:
        value = fields.Datetime.now()
    observed = value if isinstance(value, datetime) else fields.Datetime.to_datetime(value)
    if observed.tzinfo is None or observed.utcoffset() is None:
        observed = observed.replace(tzinfo=timezone.utc)
    else:
        observed = observed.astimezone(timezone.utc)
    return observed.isoformat().replace("+00:00", "Z")


def _event_document(event, *, received_at=None):
    event_type = AGENT_EVENT_TYPES.get(event.event_type)
    if event_type is None:
        raise ValidationError("Unsupported agent onboarding integration event.")
    tenant_id = (event.organization_public_id or "").strip()
    if not tenant_id:
        raise ValidationError(
            "Agent events require an organization tenant identity."
        )
    return {
        "event_id": event.event_uuid,
        "event_type": event_type,
        "event_version": "1.0",
        "occurred_at": _iso_utc(event.created_at),
        "received_at": _iso_utc(
            received_at or datetime.now(timezone.utc)
        ),
        "source": "odoo-integration",
        "tenant_id": tenant_id,
        "correlation_id": event.correlation_id,
        "causation_id": event.causation_id or event.event_uuid,
        "idempotency_key": event.event_uuid,
        "payload": event.payload_json,
        "metadata": {
            "aggregate_type": event.aggregate_type,
            "aggregate_uuid": event.aggregate_uuid,
            "business_unit_code": event.business_unit_code,
            "campaign_id": str(event.campaign_id.id),
            "environment": event.record_environment,
            "odoo_outbox_key": event.deterministic_event_key,
            "payload_sha256": event.payload_hash,
            "schema_version": event.schema_version,
        },
    }


def _signed_headers(*, token, key, body, timestamp, event):
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = "\n".join(
        (
            "v1",
            "POST",
            MIDDLEWARE_EVENT_PATH,
            timestamp,
            event["event_id"],
            "odoo-integration",
            body_hash,
        )
    ).encode("utf-8")
    signature = hmac.new(key, canonical, hashlib.sha256).hexdigest()
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Idempotency-Key": event["event_id"],
        "X-Codestra-Event-Id": event["event_id"],
        "X-Codestra-Event-Type": event["event_type"],
        "X-Codestra-Source": "odoo-integration",
        "X-Codestra-Tenant-Id": event["tenant_id"],
        "X-Codestra-Timestamp": timestamp,
        "X-Codestra-Signature": f"sha256={signature}",
        "X-Correlation-Id": event["correlation_id"],
    }


def _validate_ack(document, event):
    if not isinstance(document, dict):
        raise ValidationError(
            "Middleware event acknowledgement must be a JSON object."
        )
    if (
        document.get("event_id") != event["event_id"]
        or document.get("tenant_id") != event["tenant_id"]
        or document.get("correlation_id") != event["correlation_id"]
        or document.get("status") not in {"accepted", "duplicate"}
        or not isinstance(document.get("duplicate"), bool)
    ):
        raise ValidationError(
            "Middleware event acknowledgement does not match the request."
        )
    return document


class CodestraAgentOnboardingOutboxDelivery(models.Model):
    _inherit = "codestra.runtime.integration.outbox"

    def _agent_middleware_configuration(self):
        endpoint = _event_endpoint(
            os.getenv("CODESTRA_MIDDLEWARE_ODOO_EVENTS_URL")
        )
        token = _protected_value(
            os.getenv("CODESTRA_MIDDLEWARE_ODOO_EVENTS_TOKEN_FILE"),
            "Middleware Odoo-events bearer token",
        )
        key = _protected_value(
            os.getenv("CODESTRA_MIDDLEWARE_ODOO_EVENTS_HMAC_FILE"),
            "Middleware Odoo-events HMAC key",
            binary=True,
        )
        return endpoint, token, key

    def _send_agent_event_to_middleware(self):
        self.ensure_one()
        endpoint, token, key = self._agent_middleware_configuration()
        event = _event_document(self)
        body = _canonical_json(event).encode("utf-8")
        timestamp = str(int(time.time()))
        outbound = request.Request(
            endpoint,
            data=body,
            method="POST",
            headers=_signed_headers(
                token=token,
                key=key,
                body=body,
                timestamp=timestamp,
                event=event,
            ),
        )
        context = ssl.create_default_context()
        with request.urlopen(  # nosec B310
            outbound, timeout=10, context=context
        ) as response:
            raw = response.read(MAX_ACK_BYTES + 1)
            if len(raw) > MAX_ACK_BYTES:
                raise ValidationError(
                    "Middleware acknowledgement exceeds the size limit."
                )
        try:
            document = json.loads(raw)
        except (TypeError, ValueError) as error:
            raise ValidationError(
                "Middleware acknowledgement is not valid JSON."
            ) from error
        return _validate_ack(document, event)

    def _send_to_middleware(self):
        self.ensure_one()
        if self.event_type in AGENT_EVENT_TYPES:
            return self._send_agent_event_to_middleware()
        return super()._send_to_middleware()

    def _finalize_delivery_success(self, result):
        self.ensure_one()
        if self.event_type not in AGENT_EVENT_TYPES:
            return super()._finalize_delivery_success(result)
        _validate_ack(result, _event_document(self))
        now = fields.Datetime.now()
        return self._worker_write(
            {
                "delivery_state": "delivered",
                "delivered_at": now,
                "acknowledged_at": now,
                "processing_started_at": False,
                "lease_consumer_id": False,
                "lease_token_hash": False,
                "lease_expires_at": False,
                "lease_heartbeat_at": False,
                "last_error_code": False,
                "last_error_class": False,
                "last_error_safe_message": False,
                "last_error_fingerprint": False,
                "integration_status": "PROCESSING",
            }
        )

    def _finalize_delivery_failure(self, exc):
        self.ensure_one()
        if self.event_type not in AGENT_EVENT_TYPES:
            return super()._finalize_delivery_failure(exc)
        retry_count = self.retry_count + 1
        terminal = retry_count >= 5
        self._worker_write(
            {
                "delivery_state": "failed",
                "retry_count": retry_count,
                "next_attempt_at": fields.Datetime.now()
                + timedelta(seconds=min(300, 2**retry_count)),
                "processing_started_at": False,
                "lease_consumer_id": False,
                "lease_token_hash": False,
                "lease_expires_at": False,
                "lease_heartbeat_at": False,
                "last_error_code": "AGENT_EVENT_DELIVERY_FAILED",
                "last_error_class": type(exc).__name__[:128],
                "last_error_safe_message": (
                    "Agent integration delivery failed."
                ),
                "last_error_fingerprint": hashlib.sha256(
                    type(exc).__name__.encode("utf-8")
                ).hexdigest(),
            }
        )
        if terminal:
            self._worker_write(
                {
                    "delivery_state": "dead_letter",
                    "integration_status": "FAILED",
                }
            )
        return terminal
