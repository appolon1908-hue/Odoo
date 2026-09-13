from __future__ import annotations

import hashlib
import json
import math
import re
from functools import wraps

from psycopg2.errors import SerializationFailure, UniqueViolation
from datetime import datetime, timezone

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


EVENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}$")
DIGEST_RE = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
SAFE_DIMENSION_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,63}$")
PROHIBITED_DATA_KEYS = {"body", "logs", "traces", "raw_samples", "raw_logs", "raw_traces", "samples"}
SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "cookie",
    "credential",
    "private_key",
    "api_key",
    "access_key",
    "message_body",
    "raw_sample",
    "raw_log",
    "raw_trace",
    "notification_body",
    "request_body",
    "response_body",
    "email_body",
    "phone",
    "email",
)


KPI_ENVIRONMENTS = {"development", "test", "staging", "production"}
KPI_RECONCILIATION_STATES = {"accepted", "reconciled", "drifted", "pending"}
INCIDENT_STATES = {"firing", "acknowledged", "resolved", "inhibited", "silenced"}
INCIDENT_SEVERITIES = {"critical", "high", "warning", "info"}
INCIDENT_TRANSITIONS = {
    "firing": INCIDENT_STATES,
    "acknowledged": INCIDENT_STATES,
    "resolved": {"resolved", "firing", "acknowledged"},
    "inhibited": {"inhibited", "firing", "resolved", "acknowledged", "silenced"},
    "silenced": {"silenced", "firing", "resolved", "acknowledged", "inhibited"},
}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _clean_text(value, field_name, maximum=128, *, required=True):
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be a string")
    value = value.strip()
    if required and not value:
        raise ValidationError(f"{field_name} is required")
    if len(value) > maximum or (value and not IDENTIFIER_RE.fullmatch(value)):
        raise ValidationError(f"{field_name} is malformed")
    return value


def _bounded_text(value, field_name, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValidationError(f"{field_name} is malformed")
    if any(ord(char) < 32 for char in value):
        raise ValidationError(f"{field_name} contains control characters")
    return value.strip()


def _clean_digest(value, field_name):
    if not isinstance(value, str) or not DIGEST_RE.fullmatch(value):
        raise ValidationError(f"{field_name} must be a SHA-256 digest")
    return value.removeprefix("sha256:")


def _timestamp(value, field_name, *, required=True):
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field_name} must be an RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{field_name} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{field_name} must include a timezone")
    return (
        parsed.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _document_timestamp(value):
    if not value:
        return None
    parsed = value
    if isinstance(parsed, str):
        parsed = datetime.fromisoformat(parsed.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (
        parsed.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _storage_values(values):
    values = dict(values)
    for key in (
        "period_start",
        "period_end",
        "observed_at",
        "first_seen_at",
        "last_seen_at",
        "resolved_at",
    ):
        value = values.get(key)
        if not value:
            continue
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            values[key] = fields.Datetime.to_string(
                parsed.astimezone(timezone.utc).replace(tzinfo=None)
            )
    return values


def _safe_mapping(value, field_name, *, maximum=32):
    if not isinstance(value, dict) or len(value) > maximum:
        raise ValidationError(f"{field_name} must be a bounded object")
    clean = {}
    for key, item in value.items():
        if not isinstance(key, str) or not SAFE_DIMENSION_KEY_RE.fullmatch(key):
            raise ValidationError(f"{field_name} contains an unsafe key")
        if key.lower().replace("-", "_") in PROHIBITED_DATA_KEYS or any(part in key.lower().replace("-", "_") for part in SENSITIVE_KEY_PARTS):
            raise ValidationError(f"{field_name} contains a sensitive key")
        if isinstance(item, bool):
            clean[key] = item
        elif isinstance(item, float) and not math.isfinite(item):
            raise ValidationError(f"{field_name} contains a non-finite value")
        elif isinstance(item, (int, float)) and not isinstance(item, bool):
            clean[key] = item
        elif isinstance(item, str) and len(item) <= 128 and item:
            clean[key] = item
        else:
            raise ValidationError(f"{field_name} contains an unsupported value")
    encoded = _canonical(clean).encode("utf-8")
    if len(encoded) > 8192:
        raise ValidationError(f"{field_name} exceeds the storage budget")
    return clean


def _projection_hash(payload, keys):
    return _hash({key: payload[key] for key in keys})


def _validate_projection_hash(payload, keys):
    supplied = _clean_digest(payload.get("projection_hash"), "projection_hash")
    hash_payload = dict(payload)
    source_hash = hash_payload.get("source_payload_hash")
    if isinstance(source_hash, str) and not source_hash.startswith("sha256:"):
        hash_payload["source_payload_hash"] = "sha256:" + source_hash
    expected = _projection_hash(hash_payload, keys)
    if supplied != expected:
        raise ValidationError("projection hash does not match the immutable payload")
    return expected


KPI_HASH_KEYS = (
    "event_id",
    "schema_version",
    "tenant_id",
    "metric_code",
    "service_id",
    "environment",
    "period_reference",
    "period_start",
    "period_end",
    "value",
    "unit",
    "dimensions",
    "source",
    "source_revision",
    "source_payload_hash",
    "observed_at",
    "reconciliation_state",
    "correlation_id",
)

INCIDENT_HASH_KEYS = (
    "event_id",
    "schema_version",
    "tenant_id",
    "incident_id",
    "fingerprint",
    "alertname",
    "group_key",
    "severity",
    "state",
    "service_id",
    "environment",
    "host",
    "summary",
    "labels",
    "first_seen_at",
    "last_seen_at",
    "resolved_at",
    "source_deployment",
    "resource_version",
    "source_payload_hash",
    "observed_at",
    "correlation_id",
)


TRANSPORT_FIELDS = {"operation", "idempotency_key", "causation_id"}


def _validate_fields(payload, required, operation):
    if payload.keys() - required - TRANSPORT_FIELDS:
        raise ValidationError("unknown projection fields are prohibited")
    if "operation" in payload and payload["operation"] != operation:
        raise ValidationError("projection operation does not match the endpoint")
    for field_name in ("idempotency_key", "causation_id"):
        if field_name in payload:
            _clean_text(payload[field_name], field_name)
    if payload.get("causation_id", payload.get("event_id")) != payload.get("event_id"):
        raise ValidationError("projection causation binding conflict")


def _retry_concurrent_projection(method):
    @wraps(method)
    def wrapped(self, payload):
        try:
            with self.env.cr.savepoint():
                return method(self, payload)
        except UniqueViolation as error:
            # Odoo uses REPEATABLE READ. A concurrent insert cannot be read in
            # this snapshot; let Odoo's HTTP transaction retry start a new one.
            if error.diag.constraint_name in {
                "kyyow_observability_kpi_snapshot_event_unique",
                "kyyow_observability_incident_event_event_unique",
                "kyyow_observability_incident_incident_unique",
                "kyyow_observability_incident_fingerprint_unique",
            }:
                raise SerializationFailure("concurrent observability projection; retry transaction") from error
            raise
    return wrapped


def validate_kpi_payload(payload):
    if not isinstance(payload, dict):
        raise ValidationError("KPI payload must be an object")
    required = set(KPI_HASH_KEYS) | {"projection_hash"}
    _validate_fields(payload, required, "odoo.observability.kpis.create")
    missing = sorted(required - payload.keys())
    if missing:
        raise ValidationError(f"KPI payload is missing: {', '.join(missing)}")
    event_id = _clean_text(payload["event_id"], "event_id")
    if not EVENT_ID_RE.fullmatch(event_id):
        raise ValidationError("event_id is malformed")
    schema_version = payload["schema_version"]
    if schema_version != "kyyow.observability.kpi.v1":
        raise ValidationError("unsupported KPI schema version")
    tenant_id = _clean_text(payload["tenant_id"], "tenant_id")
    metric_code = _clean_text(payload["metric_code"], "metric_code", 96)
    service_id = _clean_text(payload["service_id"], "service_id")
    environment = payload["environment"]
    if environment not in KPI_ENVIRONMENTS:
        raise ValidationError("unsupported KPI environment")
    period_reference = _clean_text(payload["period_reference"], "period_reference", 128)
    period_start = _timestamp(payload["period_start"], "period_start")
    period_end = _timestamp(payload["period_end"], "period_end")
    if period_end <= period_start:
        raise ValidationError("KPI period must be positive")
    value = payload["value"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError("KPI value must be numeric")
    if value != value or value in (float("inf"), float("-inf")):
        raise ValidationError("KPI value must be finite")
    unit = _clean_text(payload["unit"], "unit", 32)
    dimensions = _safe_mapping(payload["dimensions"], "dimensions")
    source = _clean_text(payload["source"], "source", 96)
    source_revision = payload["source_revision"]
    if isinstance(source_revision, bool) or not isinstance(source_revision, int) or source_revision < 1:
        raise ValidationError("source_revision must be positive")
    source_payload_hash = _clean_digest(
        payload["source_payload_hash"], "source_payload_hash"
    )
    observed_at = _timestamp(payload["observed_at"], "observed_at")
    reconciliation_state = payload["reconciliation_state"]
    if reconciliation_state not in KPI_RECONCILIATION_STATES:
        raise ValidationError("unsupported KPI reconciliation state")
    correlation_id = _clean_text(payload["correlation_id"], "correlation_id")
    clean = {
        "event_id": event_id,
        "schema_version": schema_version,
        "tenant_id": tenant_id,
        "metric_code": metric_code,
        "service_id": service_id,
        "environment": environment,
        "period_reference": period_reference,
        "period_start": period_start,
        "period_end": period_end,
        "value": value,
        "unit": unit,
        "dimensions": dimensions,
        "source": source,
        "source_revision": source_revision,
        "source_payload_hash": source_payload_hash,
        "observed_at": observed_at,
        "reconciliation_state": reconciliation_state,
        "correlation_id": correlation_id,
    }
    clean["projection_hash"] = _validate_projection_hash(
        {**clean, "projection_hash": payload["projection_hash"]},
        KPI_HASH_KEYS,
    )
    return clean


def validate_incident_payload(payload):
    if not isinstance(payload, dict):
        raise ValidationError("incident payload must be an object")
    required = set(INCIDENT_HASH_KEYS) | {"projection_hash"}
    _validate_fields(payload, required, "odoo.observability.incidents.upsert")
    missing = sorted(required - payload.keys())
    if missing:
        raise ValidationError(f"incident payload is missing: {', '.join(missing)}")
    event_id = _clean_text(payload["event_id"], "event_id")
    schema_version = payload["schema_version"]
    if schema_version != "kyyow.observability.incident.v1":
        raise ValidationError("unsupported incident schema version")
    tenant_id = _clean_text(payload["tenant_id"], "tenant_id")
    incident_id = _clean_text(payload["incident_id"], "incident_id")
    fingerprint = _clean_text(payload["fingerprint"], "fingerprint")
    alertname = _clean_text(payload["alertname"], "alertname", 128)
    group_key = _bounded_text(payload["group_key"], "group_key", 2048)
    severity = payload["severity"]
    state = payload["state"]
    if severity not in INCIDENT_SEVERITIES:
        raise ValidationError("unsupported incident severity")
    if state not in INCIDENT_STATES:
        raise ValidationError("unsupported incident state")
    service_id = _clean_text(payload["service_id"], "service_id")
    environment = payload["environment"]
    if environment not in KPI_ENVIRONMENTS:
        raise ValidationError("unsupported incident environment")
    host = _clean_text(payload["host"], "host", 128, required=False)
    summary = payload["summary"]
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 512:
        raise ValidationError("incident summary is malformed")
    labels = _safe_mapping(payload["labels"], "labels")
    first_seen_at = _timestamp(payload["first_seen_at"], "first_seen_at")
    last_seen_at = _timestamp(payload["last_seen_at"], "last_seen_at")
    if last_seen_at < first_seen_at:
        raise ValidationError("incident last_seen_at precedes first_seen_at")
    resolved_at = _timestamp(
        payload["resolved_at"], "resolved_at", required=False
    )
    if state == "resolved" and not resolved_at:
        raise ValidationError("resolved incidents require resolved_at")
    if state != "resolved" and resolved_at is not None:
        raise ValidationError("only resolved incidents may have resolved_at")
    source_deployment = _clean_text(
        payload["source_deployment"], "source_deployment", 128
    )
    resource_version = payload["resource_version"]
    if isinstance(resource_version, bool) or not isinstance(resource_version, int) or resource_version < 1:
        raise ValidationError("resource_version must be positive")
    source_payload_hash = _clean_digest(
        payload["source_payload_hash"], "source_payload_hash"
    )
    observed_at = _timestamp(payload["observed_at"], "observed_at")
    correlation_id = _clean_text(payload["correlation_id"], "correlation_id")
    clean = {
        "event_id": event_id,
        "schema_version": schema_version,
        "tenant_id": tenant_id,
        "incident_id": incident_id,
        "fingerprint": fingerprint,
        "alertname": alertname,
        "group_key": group_key,
        "severity": severity,
        "state": state,
        "service_id": service_id,
        "environment": environment,
        "host": host,
        "summary": summary.strip(),
        "labels": labels,
        "first_seen_at": first_seen_at,
        "last_seen_at": last_seen_at,
        "resolved_at": resolved_at,
        "source_deployment": source_deployment,
        "resource_version": resource_version,
        "source_payload_hash": source_payload_hash,
        "observed_at": observed_at,
        "correlation_id": correlation_id,
    }
    clean["projection_hash"] = _validate_projection_hash(
        {**clean, "projection_hash": payload["projection_hash"]},
        INCIDENT_HASH_KEYS,
    )
    return clean


class KyyowObservabilityKpiSnapshot(models.Model):
    _name = "kyyow.observability.kpi.snapshot"
    _description = "Kyyow Observability KPI Snapshot"
    _order = "period_end desc, observed_at desc, id desc"

    event_id = fields.Char(required=True, index=True, readonly=True, copy=False)
    schema_version = fields.Char(required=True, readonly=True, copy=False)
    tenant_id = fields.Char(required=True, index=True, readonly=True, copy=False)
    metric_code = fields.Char(required=True, index=True, readonly=True, copy=False)
    service_id = fields.Char(required=True, index=True, readonly=True, copy=False)
    environment = fields.Selection(
        [(value, value.title()) for value in sorted(KPI_ENVIRONMENTS)],
        required=True,
        index=True,
        readonly=True,
        copy=False,
    )
    period_reference = fields.Char(required=True, index=True, readonly=True, copy=False)
    period_start = fields.Datetime(required=True, readonly=True, copy=False)
    period_end = fields.Datetime(required=True, readonly=True, copy=False)
    value = fields.Float(required=True, readonly=True, copy=False)
    unit = fields.Char(required=True, readonly=True, copy=False)
    dimensions = fields.Json(required=True, readonly=True, copy=False)
    source = fields.Char(required=True, readonly=True, copy=False)
    source_revision = fields.Integer(required=True, readonly=True, copy=False)
    source_payload_hash = fields.Char(required=True, size=64, readonly=True, copy=False)
    observed_at = fields.Datetime(required=True, readonly=True, copy=False)
    reconciliation_state = fields.Selection(
        [(value, value.title()) for value in sorted(KPI_RECONCILIATION_STATES)],
        required=True,
        readonly=True,
        copy=False,
    )
    correlation_id = fields.Char(required=True, index=True, readonly=True, copy=False)
    projection_hash = fields.Char(required=True, size=64, index=True, readonly=True, copy=False)
    created_at = fields.Datetime(
        required=True, default=fields.Datetime.now, index=True, readonly=True, copy=False
    )

    _event_unique = models.Constraint(
        "UNIQUE(event_id)", "KPI event IDs must be unique."
    )
    _projection_hash_format = models.Constraint(
        "CHECK(length(projection_hash) = 64)",
        "KPI projection hashes must be SHA-256 values.",
    )

    @api.model
    @_retry_concurrent_projection
    def _from_payload(self, payload):
        clean = validate_kpi_payload(payload)
        existing = self.search([("event_id", "=", clean["event_id"])], limit=1)
        if existing:
            if existing.projection_hash != clean["projection_hash"]:
                raise ValidationError("KPI event replay has a different payload")
            return existing, True
        record = self.with_context(codestra_observability_service=True).create(clean)
        return record, False

    @api.model_create_multi
    def create(self, values_list):
        if not self.env.context.get("codestra_observability_service"):
            raise AccessError("KPI snapshots are service-managed and immutable.")
        prepared = []
        for values in values_list:
            values = _storage_values(values)
            if values.get("projection_hash") and len(values["projection_hash"]) != 64:
                raise ValidationError("KPI projection hash is invalid.")
            prepared.append(values)
        return super().create(prepared)

    def write(self, values):
        raise AccessError("KPI snapshots are immutable.")

    def unlink(self):
        raise AccessError("KPI snapshots cannot be deleted.")

    def document(self):
        self.ensure_one()
        return {
            "event_id": self.event_id,
            "schema_version": self.schema_version,
            "tenant_id": self.tenant_id,
            "metric_code": self.metric_code,
            "service_id": self.service_id,
            "environment": self.environment,
            "period_reference": self.period_reference,
            "period_start": _document_timestamp(self.period_start),
            "period_end": _document_timestamp(self.period_end),
            "value": self.value,
            "unit": self.unit,
            "dimensions": self.dimensions or {},
            "source": self.source,
            "source_revision": self.source_revision,
            "source_payload_hash": f"sha256:{self.source_payload_hash}",
            "observed_at": _document_timestamp(self.observed_at),
            "reconciliation_state": self.reconciliation_state,
            "correlation_id": self.correlation_id,
            "projection_hash": f"sha256:{self.projection_hash}",
            "created_at": _document_timestamp(self.created_at),
        }


class KyyowObservabilityIncident(models.Model):
    _name = "kyyow.observability.incident"
    _description = "Kyyow Observability Incident"
    _order = "last_seen_at desc, id desc"

    incident_id = fields.Char(required=True, index=True, readonly=True, copy=False)
    tenant_id = fields.Char(required=True, index=True, readonly=True, copy=False)
    fingerprint = fields.Char(required=True, index=True, readonly=True, copy=False)
    alertname = fields.Char(required=True, index=True, readonly=True, copy=False)
    group_key = fields.Char(required=True, readonly=True, copy=False)
    severity = fields.Selection(
        [(value, value.title()) for value in sorted(INCIDENT_SEVERITIES)],
        required=True,
        index=True,
        readonly=True,
        copy=False,
    )
    state = fields.Selection(
        [(value, value.title()) for value in sorted(INCIDENT_STATES)],
        required=True,
        index=True,
        readonly=True,
        copy=False,
    )
    service_id = fields.Char(required=True, index=True, readonly=True, copy=False)
    environment = fields.Selection(
        [(value, value.title()) for value in sorted(KPI_ENVIRONMENTS)],
        required=True,
        index=True,
        readonly=True,
        copy=False,
    )
    host = fields.Char(readonly=True, copy=False)
    summary = fields.Char(required=True, readonly=True, copy=False)
    labels = fields.Json(required=True, readonly=True, copy=False)
    first_seen_at = fields.Datetime(required=True, readonly=True, copy=False)
    last_seen_at = fields.Datetime(required=True, readonly=True, copy=False)
    resolved_at = fields.Datetime(readonly=True, copy=False)
    source_deployment = fields.Char(required=True, readonly=True, copy=False)
    resource_version = fields.Integer(required=True, readonly=True, copy=False)
    source_payload_hash = fields.Char(required=True, size=64, readonly=True, copy=False)
    observed_at = fields.Datetime(required=True, readonly=True, copy=False)
    correlation_id = fields.Char(required=True, index=True, readonly=True, copy=False)
    projection_hash = fields.Char(required=True, size=64, index=True, readonly=True, copy=False)
    created_at = fields.Datetime(
        required=True, default=fields.Datetime.now, index=True, readonly=True, copy=False
    )
    updated_at = fields.Datetime(
        required=True, default=fields.Datetime.now, index=True, readonly=True, copy=False
    )

    _incident_unique = models.Constraint(
        "UNIQUE(tenant_id,incident_id)",
        "Incident identities are tenant scoped and unique.",
    )
    _fingerprint_unique = models.Constraint(
        "UNIQUE(tenant_id,fingerprint)",
        "Incident fingerprints are tenant scoped and unique.",
    )
    _hash_format = models.Constraint(
        "CHECK(length(projection_hash) = 64)",
        "Incident projection hashes must be SHA-256 values.",
    )

    @api.model
    @_retry_concurrent_projection
    def _from_payload(self, payload):
        clean = validate_incident_payload(payload)
        event_model = self.env["kyyow.observability.incident.event"]
        prior_event = event_model.search([("event_id", "=", clean["event_id"])], limit=1)
        if prior_event:
            if prior_event.projection_hash != clean["projection_hash"]:
                raise ValidationError("incident event replay has a different payload")
            return prior_event.incident_id, True
        # Serialize updates before reading the current version. PostgreSQL
        # raises a serialization failure if a concurrent writer changed a row
        # since this transaction's snapshot; Odoo retries the entire request.
        self.env.cr.execute(
            "SELECT id FROM kyyow_observability_incident WHERE tenant_id=%s AND incident_id=%s FOR UPDATE",
            (clean["tenant_id"], clean["incident_id"]),
        )
        locked = self.env.cr.fetchone()
        if locked:
            self.browse(locked[0]).invalidate_recordset()
        fingerprint_owner = self.search([
            ("tenant_id", "=", clean["tenant_id"]),
            ("fingerprint", "=", clean["fingerprint"]),
        ], limit=1)
        if fingerprint_owner and fingerprint_owner.incident_id != clean["incident_id"]:
            raise ValidationError("incident fingerprint is already bound")
        incident = self.search(
            [
                ("tenant_id", "=", clean["tenant_id"]),
                ("incident_id", "=", clean["incident_id"]),
            ],
            limit=1,
        )
        previous_state = incident.state if incident else False
        if incident and clean["resource_version"] <= incident.resource_version:
            raise ValidationError("incident resource version is stale")
        if incident and clean["state"] not in INCIDENT_TRANSITIONS.get(
            incident.state, set()
        ):
            raise ValidationError(
                f"illegal incident transition: {incident.state} -> {clean['state']}"
            )
        values = {
            key: clean[key]
            for key in (
                "tenant_id",
                "incident_id",
                "fingerprint",
                "alertname",
                "group_key",
                "severity",
                "state",
                "service_id",
                "environment",
                "host",
                "summary",
                "labels",
                "first_seen_at",
                "last_seen_at",
                "resolved_at",
                "source_deployment",
                "resource_version",
                "source_payload_hash",
                "observed_at",
                "correlation_id",
                "projection_hash",
            )
        }
        values["updated_at"] = fields.Datetime.now()
        if incident:
            incident.with_context(codestra_observability_service=True).write(values)
        else:
            incident = self.with_context(
                codestra_observability_service=True
            ).create(values)
        event_model.with_context(codestra_observability_service=True).create(
            {
                "event_id": clean["event_id"],
                "receipt": {
                    "status": "APPLIED",
                    "operation": "odoo.observability.incidents.upsert",
                    "event_id": clean["event_id"],
                    "tenant_id": clean["tenant_id"],
                    "incident_id": clean["incident_id"],
                    "state": clean["state"],
                    "resource_version": clean["resource_version"],
                    "correlation_id": clean["correlation_id"],
                    "receipt_id": f"kyyow-incident-{incident.id}-{clean['resource_version']}",
                },
                "incident_id": incident.id,
                "tenant_id": clean["tenant_id"],
                "previous_state": previous_state or False,
                "new_state": clean["state"],
                "resource_version": clean["resource_version"],
                "projection_hash": clean["projection_hash"],
                "correlation_id": clean["correlation_id"],
                "source_deployment": clean["source_deployment"],
                "observed_at": clean["observed_at"],
            }
        )
        return incident, False

    @api.model_create_multi
    def create(self, values_list):
        if not self.env.context.get("codestra_observability_service"):
            raise AccessError("Incidents are service-managed and immutable.")
        return super().create([_storage_values(values) for values in values_list])

    def write(self, values):
        if not self.env.context.get("codestra_observability_service"):
            raise AccessError("Incidents are service-managed and immutable.")
        protected = set(values) - {"updated_at"}
        if protected and not self.env.context.get("codestra_observability_service"):
            raise AccessError("Incident state is service-managed.")
        return super().write(_storage_values(values))

    def unlink(self):
        raise AccessError("Incidents cannot be deleted.")

    def document(self):
        self.ensure_one()
        return {
            "incident_id": self.incident_id,
            "tenant_id": self.tenant_id,
            "fingerprint": self.fingerprint,
            "alertname": self.alertname,
            "group_key": self.group_key,
            "severity": self.severity,
            "state": self.state,
            "service_id": self.service_id,
            "environment": self.environment,
            "host": self.host or None,
            "summary": self.summary,
            "labels": self.labels or {},
            "first_seen_at": _document_timestamp(self.first_seen_at),
            "last_seen_at": _document_timestamp(self.last_seen_at),
            "resolved_at": _document_timestamp(self.resolved_at)
            if self.resolved_at
            else None,
            "source_deployment": self.source_deployment,
            "resource_version": self.resource_version,
            "source_payload_hash": f"sha256:{self.source_payload_hash}",
            "observed_at": _document_timestamp(self.observed_at),
            "correlation_id": self.correlation_id,
            "projection_hash": f"sha256:{self.projection_hash}",
            "updated_at": _document_timestamp(self.updated_at),
        }


class KyyowObservabilityIncidentEvent(models.Model):
    _name = "kyyow.observability.incident.event"
    _description = "Kyyow Observability Incident Transition"
    _order = "id desc"

    receipt = fields.Json(required=True, readonly=True, copy=False)
    event_id = fields.Char(required=True, index=True, readonly=True, copy=False)
    incident_id = fields.Many2one(
        "kyyow.observability.incident",
        required=True,
        ondelete="restrict",
        index=True,
        readonly=True,
        copy=False,
    )
    tenant_id = fields.Char(required=True, index=True, readonly=True, copy=False)
    previous_state = fields.Selection(
        [(value, value.title()) for value in sorted(INCIDENT_STATES)],
        readonly=True,
        copy=False,
    )
    new_state = fields.Selection(
        [(value, value.title()) for value in sorted(INCIDENT_STATES)],
        required=True,
        readonly=True,
        copy=False,
    )
    resource_version = fields.Integer(required=True, readonly=True, copy=False)
    projection_hash = fields.Char(required=True, size=64, readonly=True, copy=False)
    correlation_id = fields.Char(required=True, index=True, readonly=True, copy=False)
    source_deployment = fields.Char(required=True, readonly=True, copy=False)
    observed_at = fields.Datetime(required=True, readonly=True, copy=False)
    created_at = fields.Datetime(
        required=True, default=fields.Datetime.now, index=True, readonly=True, copy=False
    )

    _event_unique = models.Constraint(
        "UNIQUE(event_id)", "Incident event IDs must be unique."
    )

    @api.model_create_multi
    def create(self, values_list):
        if not self.env.context.get("codestra_observability_service"):
            raise AccessError("Incident transitions are service-managed and immutable.")
        return super().create([_storage_values(values) for values in values_list])

    def write(self, values):
        raise AccessError("Incident transitions are immutable.")

    def unlink(self):
        raise AccessError("Incident transitions cannot be deleted.")

    def document(self):
        self.ensure_one()
        return {
            "event_id": self.event_id,
            "incident_id": self.incident_id.incident_id,
            "tenant_id": self.tenant_id,
            "previous_state": self.previous_state or None,
            "new_state": self.new_state,
            "resource_version": self.resource_version,
            "projection_hash": f"sha256:{self.projection_hash}",
            "correlation_id": self.correlation_id,
            "source_deployment": self.source_deployment,
            "observed_at": _document_timestamp(self.observed_at),
            "created_at": _document_timestamp(self.created_at),
        }
