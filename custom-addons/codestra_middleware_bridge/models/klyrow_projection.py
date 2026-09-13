from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


EVENT_TYPES = frozenset(
    {
        "klyrow.tenant.created",
        "klyrow.tenant.updated",
        "klyrow.subscription.changed",
        "klyrow.usage.daily",
        "klyrow.kpi.daily",
        "klyrow.campaign.summary",
        "klyrow.domain.status",
        "klyrow.provider.health",
        "klyrow.account.held",
        "klyrow.account.released",
    }
)


def _text(value, name, maximum=200):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ValidationError(f"{name} is invalid")
    if any(ord(character) < 32 for character in value):
        raise ValidationError(f"{name} contains control characters")
    return value


def _timestamp(value, name):
    value = _text(value, name, 40)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{name} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


class KlyrowBusinessProjection(models.Model):
    _name = "codestra.klyrow.business.projection"
    _description = "Klyrow Business Projection"
    _order = "tenant_id, event_family, logical_key"

    tenant_id = fields.Char(required=True, index=True, readonly=True)
    event_family = fields.Selection(
        [
            ("tenant", "Tenant"),
            ("subscription", "Subscription"),
            ("usage_daily", "Daily Usage"),
            ("kpi_daily", "Daily KPI"),
            ("campaign", "Campaign"),
            ("domain", "Domain"),
            ("provider", "Provider"),
            ("account", "Account"),
        ],
        required=True,
        index=True,
        readonly=True,
    )
    logical_key = fields.Char(required=True, index=True, readonly=True)
    operation_id = fields.Char(required=True, index=True, readonly=True)
    last_event_id = fields.Char(required=True, index=True, readonly=True)
    event_type = fields.Char(required=True, index=True, readonly=True)
    correlation_id = fields.Char(required=True, index=True, readonly=True)
    causation_id = fields.Char(readonly=True)
    projection_version = fields.Integer(default=0, readonly=True)
    snapshot_at = fields.Datetime(index=True, readonly=True)
    occurred_at = fields.Datetime(required=True, index=True, readonly=True)
    status = fields.Char(index=True, readonly=True)
    payload_sha256 = fields.Char(required=True, readonly=True)
    data_json = fields.Text(required=True, readonly=True)

    _logical_unique = models.Constraint(
        "UNIQUE(tenant_id,event_family,logical_key)",
        "Klyrow business projections are unique by tenant and logical identity.",
    )
    _operation_unique = models.Constraint(
        "UNIQUE(operation_id)",
        "Klyrow projection operation IDs must be unique.",
    )

    @api.model
    def _normalized(self, payload, payload_sha256):
        if not isinstance(payload, dict) or set(payload) != {
            "operation_id",
            "event_id",
            "event_type",
            "event_version",
            "source",
            "tenant_id",
            "correlation_id",
            "causation_id",
            "occurred_at",
            "data",
            "trace_context",
        }:
            raise ValidationError("Klyrow projection envelope is invalid")
        event_type = payload.get("event_type")
        if event_type not in EVENT_TYPES:
            raise ValidationError("Klyrow projection event type is unsupported")
        if payload.get("event_version") != 1 or payload.get("source") != "klyrow":
            raise ValidationError("Klyrow projection source or version is invalid")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValidationError("Klyrow projection data must be an object")
        raw_data = json.dumps(data, separators=(",", ":"), sort_keys=True)
        if len(raw_data.encode()) > 65536:
            raise ValidationError("Klyrow projection data is too large")

        tenant_id = _text(payload.get("tenant_id"), "tenant_id", 200)
        operation_id = _text(payload.get("operation_id"), "operation_id", 35)
        if not re.fullmatch(r"op_[0-9a-f]{32}", operation_id):
            raise ValidationError("operation_id is invalid")
        event_id = _text(payload.get("event_id"), "event_id", 200)
        correlation_id = _text(payload.get("correlation_id"), "correlation_id", 200)
        causation_id = payload.get("causation_id")
        if causation_id is not None:
            causation_id = _text(causation_id, "causation_id", 200)
        occurred_at = _timestamp(payload.get("occurred_at"), "occurred_at")

        family = event_type.split(".")[1]
        version = 0
        snapshot_at = occurred_at
        status = data.get("status")
        if event_type.startswith("klyrow.tenant."):
            family, logical_key = "tenant", tenant_id
            if data.get("tenant_id") != tenant_id:
                raise ValidationError("tenant event identity is inconsistent")
        elif event_type == "klyrow.subscription.changed":
            family = "subscription"
            logical_key = _text(data.get("subscription_id"), "subscription_id")
            version = data.get("version")
            if isinstance(version, bool) or not isinstance(version, int) or version < 1:
                raise ValidationError("subscription version is invalid")
            snapshot_at = _timestamp(data.get("effective_at"), "effective_at")
        elif event_type in {"klyrow.usage.daily", "klyrow.kpi.daily"}:
            family = "usage_daily" if event_type == "klyrow.usage.daily" else "kpi_daily"
            date_value = _text(data.get("date"), "date", 10)
            logical_key = (
                f"{date_value}:{_text(data.get('unit'), 'unit', 40)}"
                if family == "usage_daily"
                else date_value
            )
            snapshot_at = _timestamp(data.get("snapshot_at"), "snapshot_at")
        elif event_type == "klyrow.campaign.summary":
            family = "campaign"
            logical_key = _text(data.get("campaign_id"), "campaign_id")
            version = data.get("campaign_version")
            if isinstance(version, bool) or not isinstance(version, int) or version < 1:
                raise ValidationError("campaign version is invalid")
        elif event_type == "klyrow.domain.status":
            family = "domain"
            logical_key = _text(data.get("domain_id"), "domain_id")
        elif event_type == "klyrow.provider.health":
            family = "provider"
            logical_key = _text(data.get("provider"), "provider", 100)
            snapshot_at = _timestamp(data.get("checked_at"), "checked_at")
        else:
            family, logical_key = "account", tenant_id
        if status is not None:
            status = _text(status, "status", 50)
        payload_sha256 = _text(payload_sha256, "payload_sha256", 64)
        if not re.fullmatch(r"[0-9a-f]{64}", payload_sha256):
            raise ValidationError("payload_sha256 is invalid")
        return {
            "tenant_id": tenant_id,
            "event_family": family,
            "logical_key": logical_key,
            "operation_id": operation_id,
            "last_event_id": event_id,
            "event_type": event_type,
            "correlation_id": correlation_id,
            "causation_id": causation_id,
            "projection_version": version,
            "snapshot_at": snapshot_at,
            "occurred_at": occurred_at,
            "status": status,
            "payload_sha256": payload_sha256,
            "data_json": raw_data,
        }

    @api.model
    def apply_event(self, payload, payload_sha256):
        values = self._normalized(payload, payload_sha256)
        tenant_id = values["tenant_id"]
        family = values["event_family"]
        logical_key = values["logical_key"]
        if family != "tenant":
            tenant = self.search(
                [
                    ("tenant_id", "=", tenant_id),
                    ("event_family", "=", "tenant"),
                    ("logical_key", "=", tenant_id),
                ],
                limit=1,
            )
            if not tenant:
                return None, "tenant_projection_missing"
        existing = self.search(
            [
                ("tenant_id", "=", tenant_id),
                ("event_family", "=", family),
                ("logical_key", "=", logical_key),
            ],
            limit=1,
        )
        if not existing:
            if values["event_type"] == "klyrow.tenant.updated":
                return None, "tenant_projection_missing"
            return self.create(values), "created"
        versioned = family in {"subscription", "campaign"}
        stale = (
            values["projection_version"] <= existing.projection_version
            if versioned
            else values["snapshot_at"] <= existing.snapshot_at
        )
        if stale:
            return existing, "ignored_stale"
        existing.write(values)
        return existing, "updated"

    def unlink(self):
        raise AccessError("Klyrow business projections cannot be deleted.")
