from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import unicodedata
import urllib.parse
from datetime import datetime, timezone

from psycopg2.errors import SerializationFailure, UniqueViolation

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


MAX_EVENT_BYTES = 1_048_576
MAX_RESULTS = 1_000
ALLOWED_EVENT_TYPES = frozenset(
    {
        "codestra.crawler.job.completed",
        "codestra.crawler.result.review_required",
    }
)
ALLOWED_CAPTURE_METHODS = frozenset({"http", "browser"})
FORBIDDEN_KEYS = frozenset(
    {
        "access_key",
        "access_token",
        "api_key",
        "auth_token",
        "authorization",
        "bearer_token",
        "client_secret",
        "cookie",
        "credential",
        "credentials",
        "password",
        "private_key",
        "provider_token",
        "refresh_token",
        "secret",
        "session_token",
        "set_cookie",
        "token",
    }
)
FORBIDDEN_KEY_SUFFIXES = (
    "_api_key",
    "_authorization",
    "_cookie",
    "_credential",
    "_credentials",
    "_password",
    "_private_key",
    "_secret",
    "_token",
)
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"
)
HOST_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
INVALID_PERCENT_ESCAPE_RE = re.compile(r"%(?![0-9A-Fa-f]{2})")
INTERNAL_CONTEXT = "codestra_kyqra_internal"
# Process-local capability; RPC context values cannot supply this object identity.
_INTERNAL_CAPABILITY = object()
REVIEWER_GROUP = "codestra_kyqra_review_hub.group_kyqra_reviewer"
SERVICE_GROUP = "codestra_kyqra_review_hub.group_kyqra_service"


def _canonical_json(value):
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValidationError(_("Kyqra payload must be valid JSON.")) from exc


def _text(value, label, maximum=256):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(_("%s must be a non-empty string.") % label)
    value = value.strip()
    if len(value) > maximum:
        raise ValidationError(_("%s exceeds its maximum length.") % label)
    return value


def _optional_text(value, label, maximum=256):
    if value in (None, False, ""):
        return ""
    return _text(value, label, maximum)


def _identifier(value, label):
    value = _text(value, label)
    if IDENTIFIER_RE.fullmatch(value) is None:
        raise ValidationError(_("%s contains unsupported characters.") % label)
    return value


def _has_unsafe_url_character(value):
    return any(
        character == "\\"
        or character.isspace()
        or unicodedata.category(character).startswith("C")
        for character in value
    )


def _valid_hostname(hostname):
    if not hostname or "%" in hostname:
        return False
    try:
        ipaddress.ip_address(hostname)
        return True
    except ValueError:
        pass
    candidate = hostname[:-1] if hostname.endswith(".") else hostname
    try:
        ascii_hostname = candidate.encode("idna").decode("ascii")
    except UnicodeError:
        return False
    if not ascii_hostname or len(ascii_hostname) > 253:
        return False
    labels = ascii_hostname.split(".")
    if all(label.isdigit() for label in labels):
        return False
    return all(HOST_LABEL_RE.fullmatch(label) is not None for label in labels)


def _safe_url(value, label):
    value = _text(value, label, 2_048)
    if _has_unsafe_url_character(value) or INVALID_PERCENT_ESCAPE_RE.search(value):
        raise ValidationError(_("%s must be a well-formed HTTPS URL.") % label)
    try:
        parsed = urllib.parse.urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except (UnicodeError, ValueError) as exc:
        raise ValidationError(_("%s must be a well-formed HTTPS URL.") % label) from exc
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or not hostname
        or parsed.username
        or parsed.password
        or parsed.netloc.endswith(":")
        or (port is not None and port == 0)
        or not _valid_hostname(hostname)
    ):
        raise ValidationError(
            _("%s must be a well-formed HTTPS URL without credentials.") % label
        )
    for component in (parsed.netloc, parsed.path, parsed.query, parsed.fragment):
        try:
            decoded_component = urllib.parse.unquote(component, errors="strict")
        except UnicodeDecodeError as exc:
            raise ValidationError(_("%s must be a well-formed HTTPS URL.") % label) from exc
        if _has_unsafe_url_character(decoded_component):
            raise ValidationError(_("%s must be a well-formed HTTPS URL.") % label)
    for component in (parsed.query, parsed.fragment):
        try:
            parameters = urllib.parse.parse_qsl(
                component.replace(";", "&"),
                keep_blank_values=True,
                max_num_fields=100,
            )
        except ValueError as exc:
            raise ValidationError(
                _("%s contains an invalid or excessive URL parameter set.") % label
            ) from exc
        if any(_is_forbidden_key(key) for key, _value in parameters):
            raise ValidationError(
                _("%s must not contain credential-bearing URL parameters.") % label
            )
    return value


def _normalized_key(value):
    key = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", str(value))
    key = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    return re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")


def _is_forbidden_key(value):
    normalized_key = _normalized_key(value)
    return (
        normalized_key in FORBIDDEN_KEYS
        or normalized_key.endswith(FORBIDDEN_KEY_SUFFIXES)
    )


def _contains_forbidden_key(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if _is_forbidden_key(key):
                return True
            if _contains_forbidden_key(child):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_key(child) for child in value)
    return False


def _rfc3339(value, label):
    value = _text(value, label, 80)
    if RFC3339_RE.fullmatch(value) is None:
        raise ValidationError(
            _("%s must be a timezone-aware RFC3339 timestamp.") % label
        )
    iso_value = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(iso_value)
    except ValueError as exc:
        raise ValidationError(
            _("%s must be a valid RFC3339 timestamp.") % label
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValidationError(
            _("%s must include an explicit timezone offset.") % label
        )
    timespec = "microseconds" if parsed.microsecond else "seconds"
    return (
        parsed.astimezone(timezone.utc)
        .isoformat(timespec=timespec)
        .replace("+00:00", "Z")
    )


def _non_negative_int(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValidationError(_("%s must be a non-negative integer.") % label)
    return value


class CodestraKyqraBatch(models.Model):
    _name = "codestra.kyqra.batch"
    _description = "Codestra Kyqra Crawler Review Batch"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"
    _rec_name = "job_id"
    _check_company_auto = True

    tenant_id = fields.Char(required=True, index=True, readonly=True, copy=False)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        index=True,
        readonly=True,
        default=lambda self: self.env.company,
    )
    event_id = fields.Char(required=True, index=True, readonly=True, copy=False)
    event_type = fields.Char(required=True, readonly=True, copy=False)
    event_version = fields.Char(required=True, readonly=True, copy=False)
    job_id = fields.Char(required=True, index=True, readonly=True, copy=False)
    correlation_id = fields.Char(required=True, index=True, readonly=True, copy=False)
    causation_id = fields.Char(required=True, index=True, readonly=True, copy=False)
    idempotency_key = fields.Char(required=True, index=True, readonly=True, copy=False)
    source_system = fields.Char(
        required=True,
        default="kyqra-gateway",
        readonly=True,
        copy=False,
    )
    occurred_at = fields.Char(required=True, readonly=True, copy=False)
    received_at = fields.Char(required=True, readonly=True, copy=False)
    result_count = fields.Integer(required=True, readonly=True, copy=False)
    review_required = fields.Boolean(
        required=True,
        default=True,
        readonly=True,
        copy=False,
        tracking=True,
    )
    allow_external_contact = fields.Boolean(
        required=True,
        default=False,
        readonly=True,
        copy=False,
        tracking=True,
    )
    state = fields.Selection(
        [
            ("review_pending", "Review Pending"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        required=True,
        default="review_pending",
        index=True,
        readonly=True,
        copy=False,
        tracking=True,
    )
    reviewed_by_id = fields.Many2one(
        "res.users",
        readonly=True,
        copy=False,
        tracking=True,
    )
    reviewed_at = fields.Datetime(readonly=True, copy=False)
    event_digest = fields.Char(required=True, index=True, readonly=True, copy=False)
    progress_json = fields.Json(readonly=True, copy=False)
    provenance_json = fields.Json(readonly=True, copy=False)
    metadata_json = fields.Json(readonly=True, copy=False)
    raw_event_json = fields.Json(required=True, readonly=True, copy=False)
    entity_ids = fields.One2many(
        "codestra.kyqra.entity",
        "batch_id",
        string="Entities",
        readonly=True,
    )

    _event_unique = models.Constraint(
        "UNIQUE(tenant_id,event_id)",
        "A Kyqra event can be applied only once per tenant.",
    )
    _idempotency_unique = models.Constraint(
        "UNIQUE(tenant_id,idempotency_key)",
        "A Kyqra idempotency key can be applied only once per tenant.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not (
            self.env.context.get(INTERNAL_CONTEXT) is _INTERNAL_CAPABILITY
            and self.env.user.has_group(SERVICE_GROUP)
        ):
            raise AccessError(
                _("Kyqra batches can be created only by the governed service method.")
            )
        for values in vals_list:
            if values.get("review_required") is not True:
                raise ValidationError(_("Kyqra batches must remain review required."))
            if values.get("allow_external_contact") is not False:
                raise ValidationError(
                    _("Kyqra batches cannot enable external contact.")
                )
        return super().create(vals_list)

    def write(self, values):
        if not (
            self.env.context.get(INTERNAL_CONTEXT) is _INTERNAL_CAPABILITY
            and self.env.user.has_group(REVIEWER_GROUP)
        ):
            raise AccessError(_("Kyqra batch evidence is immutable."))
        allowed = {"state", "reviewed_by_id", "reviewed_at"}
        if set(values) - allowed:
            raise AccessError(_("Only governed review fields may change."))
        return super().write(values)

    def unlink(self):
        raise AccessError(_("Kyqra batches are retained and cannot be deleted."))

    @api.model
    def _assert_service_authority(self, tenant_id):
        if not self.env.user.has_group(SERVICE_GROUP):
            raise AccessError(_("Kyqra ingestion requires the dedicated service group."))
        params = self.env["ir.config_parameter"].sudo()
        allowed_tenants = {
            item.strip()
            for item in (params.get_param("codestra.kyqra.tenant_ids") or "").split(",")
            if item.strip()
        }
        if tenant_id not in allowed_tenants:
            raise AccessError(_("The Kyqra tenant is not authorized."))
        binding_key = (
            f"codestra.middleware.tenant.{tenant_id}."
            "codestra.kyqra.service_user_id"
        )
        try:
            service_user_id = int(params.get_param(binding_key, "0"))
        except (TypeError, ValueError):
            service_user_id = 0
        if service_user_id != self.env.user.id:
            raise AccessError(_("The Kyqra tenant is not bound to this service principal."))
        company_key = f"codestra.kyqra.tenant.{tenant_id}.company_id"
        try:
            company_id = int(params.get_param(company_key, "0"))
        except (TypeError, ValueError):
            company_id = 0
        company = self.env["res.company"].sudo().browse(company_id)
        if not company.exists():
            raise AccessError(_("The Kyqra tenant has no valid company binding."))
        return company

    @api.model
    def _validate_event(self, envelope):
        if not isinstance(envelope, dict):
            raise ValidationError(_("Kyqra event envelope must be an object."))
        if _contains_forbidden_key(envelope):
            raise ValidationError(_("Kyqra event contains forbidden secret material."))
        encoded = _canonical_json(envelope)
        if len(encoded) > MAX_EVENT_BYTES:
            raise ValidationError(_("Kyqra event exceeds 1 MiB."))
        allowed_fields = {
            "event_id",
            "event_type",
            "event_version",
            "occurred_at",
            "received_at",
            "source",
            "tenant_id",
            "customer_id",
            "correlation_id",
            "causation_id",
            "idempotency_key",
            "payload",
            "metadata",
        }
        unknown = set(envelope) - allowed_fields
        if unknown:
            raise ValidationError(
                _("Kyqra event contains unsupported fields: %s")
                % ", ".join(sorted(unknown))
            )
        for field_name in (
            "event_id",
            "event_type",
            "event_version",
            "occurred_at",
            "received_at",
            "source",
            "tenant_id",
            "correlation_id",
            "causation_id",
            "idempotency_key",
        ):
            if field_name not in envelope:
                raise ValidationError(_("Kyqra event is missing %s.") % field_name)
        event_id = _identifier(envelope["event_id"], "event_id")
        event_type = _text(envelope["event_type"], "event_type", 180)
        if event_type not in ALLOWED_EVENT_TYPES:
            raise ValidationError(_("Kyqra event type is not accepted."))
        if envelope["event_version"] != "1.0":
            raise ValidationError(_("Kyqra event version must be 1.0."))
        if envelope["source"] != "kyqra-gateway":
            raise ValidationError(_("Kyqra event source is not authorized."))
        tenant_id = _identifier(envelope["tenant_id"], "tenant_id")
        correlation_id = _identifier(envelope["correlation_id"], "correlation_id")
        causation_id = _identifier(envelope["causation_id"], "causation_id")
        idempotency_key = _identifier(envelope["idempotency_key"], "idempotency_key")
        occurred_at = _rfc3339(envelope["occurred_at"], "occurred_at")
        received_at = _rfc3339(envelope["received_at"], "received_at")
        if envelope.get("customer_id") not in (None, False):
            _optional_text(envelope["customer_id"], "customer_id", 256)
        if not isinstance(envelope.get("metadata"), dict):
            raise ValidationError(_("Kyqra metadata must be an object."))
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            raise ValidationError(_("Kyqra payload must be an object."))
        if set(payload) - {"job_id", "status", "error", "progress", "results"}:
            raise ValidationError(_("Kyqra payload contains unsupported fields."))
        if payload.get("status") != "completed" or payload.get("error") is not None:
            raise ValidationError(_("Only successful crawler completions enter review."))
        job_id = _identifier(payload.get("job_id"), "payload.job_id")
        progress = payload.get("progress")
        if not isinstance(progress, dict) or set(progress) != {"processed", "records", "failed"}:
            raise ValidationError(_("Kyqra progress is incomplete."))
        for key in ("processed", "records", "failed"):
            _non_negative_int(progress.get(key), f"payload.progress.{key}")
        results = payload.get("results")
        if not isinstance(results, list) or len(results) > MAX_RESULTS:
            raise ValidationError(
                _("Kyqra results must be an array of at most 1000 items.")
            )
        normalized_results = []
        seen_record_ids = set()
        for index, item in enumerate(results):
            label = f"payload.results[{index}]"
            if not isinstance(item, dict):
                raise ValidationError(_("%s must be an object.") % label)
            if set(item) - {
                "record_id",
                "source_url",
                "data",
                "provenance",
                "review_required",
                "confidence",
                "capture_method",
            }:
                raise ValidationError(_("%s contains unsupported fields.") % label)
            record_id = _identifier(item.get("record_id"), f"{label}.record_id")
            if record_id in seen_record_ids:
                raise ValidationError(
                    _("Kyqra record IDs must be unique inside a batch.")
                )
            seen_record_ids.add(record_id)
            source_url = _safe_url(item.get("source_url"), f"{label}.source_url")
            data = item.get("data")
            if not isinstance(data, dict):
                raise ValidationError(_("%s.data must be an object.") % label)
            if not isinstance(item.get("provenance"), dict):
                raise ValidationError(_("%s.provenance must be an object.") % label)
            if not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in item["provenance"].items()
            ):
                raise ValidationError(_("%s.provenance must contain strings.") % label)
            provenance = dict(item["provenance"])
            if "source_url" in provenance:
                provenance_url = _safe_url(
                    provenance["source_url"], f"{label}.provenance.source_url"
                )
                if provenance_url != source_url:
                    raise ValidationError(
                        _("%s provenance source URL must match source_url.") % label
                    )
                provenance["source_url"] = provenance_url
            if "captured_at" in provenance:
                provenance["captured_at"] = _rfc3339(
                    provenance["captured_at"], f"{label}.provenance.captured_at"
                )
            if item.get("review_required") is not True:
                raise ValidationError(
                    _("Every Kyqra result must remain review required.")
                )
            confidence = item.get("confidence")
            if confidence is not None and (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not 0 <= confidence <= 1
            ):
                raise ValidationError(
                    _("%s.confidence must be between 0 and 1.") % label
                )
            capture_method = item.get("capture_method")
            if capture_method not in ALLOWED_CAPTURE_METHODS:
                raise ValidationError(_("%s.capture_method is unsupported.") % label)
            normalized_results.append(
                {
                    "record_id": record_id,
                    "source_url": source_url,
                    "data": data,
                    "provenance": provenance,
                    "review_required": True,
                    "confidence": confidence,
                    "capture_method": capture_method,
                }
            )
        return {
            "event": envelope,
            "digest": hashlib.sha256(encoded).hexdigest(),
            "tenant_id": tenant_id,
            "event_id": event_id,
            "event_type": event_type,
            "event_version": "1.0",
            "occurred_at": occurred_at,
            "received_at": received_at,
            "idempotency_key": idempotency_key,
            "job_id": job_id,
            "correlation_id": correlation_id,
            "causation_id": causation_id,
            "progress": progress,
            "results": normalized_results,
            "metadata": dict(envelope["metadata"]),
        }

    @api.model
    def _entity_values(self, batch, item):
        data = item["data"]
        display_name = (
            data.get("name")
            or data.get("company_name")
            or data.get("title")
            or item["record_id"]
        )
        if not isinstance(display_name, str):
            display_name = item["record_id"]
        display_name = display_name.strip()[:300] or item["record_id"]
        entity_type = data.get("entity_type", "unknown")
        if not isinstance(entity_type, str):
            raise ValidationError(_("Kyqra entity_type must be a string."))
        return {
            "batch_id": batch.id,
            "record_id": item["record_id"],
            "name": display_name,
            "entity_type": entity_type[:120] or "unknown",
            "source_url": item["source_url"],
            "data_json": item["data"],
            "provenance_json": item["provenance"],
            "review_required": True,
            "confidence": item["confidence"] if item["confidence"] is not None else 0.0,
            "review_state": "review_pending",
        }

    @api.model
    def _evidence_values(self, entity, item):
        provenance = item["provenance"]
        digest = provenance.get("content_digest") or provenance.get("digest") or False
        if digest and HEX64_RE.fullmatch(digest) is None:
            raise ValidationError(_("Kyqra content digest must be lowercase SHA-256."))
        return {
            "entity_id": entity.id,
            "source_url": item["source_url"],
            "capture_method": item["capture_method"],
            "content_digest": digest,
            "locator": _optional_text(
                provenance.get("locator"), "provenance.locator", 2_048
            )
            or False,
            "quote": _optional_text(
                provenance.get("quote"), "provenance.quote", 10_000
            )
            or False,
            "captured_at": (
                _rfc3339(
                    provenance["captured_at"], "provenance.captured_at"
                )
                if provenance.get("captured_at")
                else False
            ),
        }

    @api.model
    def _result(self, batch, action):
        return {
            "action": action,
            "batch_id": batch.id,
            "event_id": batch.event_id,
            "tenant_id": batch.tenant_id,
            "job_id": batch.job_id,
            "entity_count": batch.result_count,
            "review_required": batch.review_required,
            "allow_external_contact": batch.allow_external_contact,
        }

    @api.model
    def apply_middleware_event(self, envelope):
        normalized = self._validate_event(envelope)
        company = self._assert_service_authority(normalized["tenant_id"])
        batch_model = self.sudo()
        existing = batch_model.search(
            [
                ("tenant_id", "=", normalized["tenant_id"]),
                ("event_id", "=", normalized["event_id"]),
            ],
            limit=1,
        )
        if existing:
            if existing.event_digest != normalized["digest"]:
                raise ValidationError(
                    _("event_id was already used with different content.")
                )
            return self._result(existing, "duplicate")
        prior_idempotency = batch_model.search(
            [
                ("tenant_id", "=", normalized["tenant_id"]),
                ("idempotency_key", "=", normalized["idempotency_key"]),
            ],
            limit=1,
        )
        if prior_idempotency:
            if prior_idempotency.event_digest != normalized["digest"]:
                raise ValidationError(
                    _("idempotency_key was already used with different content.")
                )
            return self._result(prior_idempotency, "duplicate")
        values = {
            "tenant_id": normalized["tenant_id"],
            "company_id": company.id,
            "event_id": normalized["event_id"],
            "event_type": normalized["event_type"],
            "event_version": normalized["event_version"],
            "job_id": normalized["job_id"],
            "correlation_id": normalized["correlation_id"],
            "causation_id": normalized["causation_id"],
            "idempotency_key": normalized["idempotency_key"],
            "source_system": "kyqra-gateway",
            "occurred_at": normalized["occurred_at"],
            "received_at": normalized["received_at"],
            "result_count": len(normalized["results"]),
            "review_required": True,
            "allow_external_contact": False,
            "state": "review_pending",
            "event_digest": normalized["digest"],
            "progress_json": normalized["progress"],
            "provenance_json": [
                item["provenance"] for item in normalized["results"]
            ],
            "metadata_json": normalized["metadata"],
            "raw_event_json": normalized["event"],
        }
        try:
            with self.env.cr.savepoint():
                batch = batch_model.with_context(**{INTERNAL_CONTEXT: _INTERNAL_CAPABILITY}).create(
                    values
                )
        except UniqueViolation as exc:
            if exc.diag.constraint_name not in {
                "codestra_kyqra_batch_event_unique",
                "codestra_kyqra_batch_idempotency_unique",
            }:
                raise
            # A savepoint rollback preserves Odoo's REPEATABLE READ snapshot.
            # Let Odoo retry the whole transaction, then the ordinary event and
            # idempotency lookups above decide duplicate versus payload conflict.
            raise SerializationFailure(
                "Concurrent Kyqra reservation requires a fresh transaction."
            ) from exc
        entity_model = self.env["codestra.kyqra.entity"].sudo()
        evidence_model = self.env["codestra.kyqra.evidence"].sudo()
        for item in normalized["results"]:
            entity = entity_model.with_context(**{INTERNAL_CONTEXT: _INTERNAL_CAPABILITY}).create(
                self._entity_values(batch, item)
            )
            evidence_model.with_context(**{INTERNAL_CONTEXT: _INTERNAL_CAPABILITY}).create(
                self._evidence_values(entity, item)
            )
        return self._result(batch, "created")

    def _assert_reviewer(self):
        if not self.env.user.has_group(REVIEWER_GROUP):
            raise AccessError(_("Kyqra review requires the reviewer group."))

    def action_approve(self):
        self._assert_reviewer()
        if any(batch.state != "review_pending" for batch in self):
            raise UserError(_("Only review-pending batches can be approved."))
        entities = self.mapped("entity_ids")
        if any(entity.review_state != "review_pending" for entity in entities):
            raise UserError(
                _("All entities must remain review pending before batch approval.")
            )
        now = fields.Datetime.now()
        self.with_context(**{INTERNAL_CONTEXT: _INTERNAL_CAPABILITY}).write(
            {
                "state": "approved",
                "reviewed_by_id": self.env.user.id,
                "reviewed_at": now,
            }
        )
        entities.with_context(**{INTERNAL_CONTEXT: _INTERNAL_CAPABILITY}).write(
            {
                "review_state": "approved",
                "reviewed_by_id": self.env.user.id,
                "reviewed_at": now,
            }
        )
        return True

    def action_reject(self):
        self._assert_reviewer()
        if any(batch.state != "review_pending" for batch in self):
            raise UserError(_("Only review-pending batches can be rejected."))
        entities = self.mapped("entity_ids")
        if any(entity.review_state != "review_pending" for entity in entities):
            raise UserError(
                _("All entities must remain review pending before batch rejection.")
            )
        now = fields.Datetime.now()
        self.with_context(**{INTERNAL_CONTEXT: _INTERNAL_CAPABILITY}).write(
            {
                "state": "rejected",
                "reviewed_by_id": self.env.user.id,
                "reviewed_at": now,
            }
        )
        entities.with_context(**{INTERNAL_CONTEXT: _INTERNAL_CAPABILITY}).write(
            {
                "review_state": "rejected",
                "reviewed_by_id": self.env.user.id,
                "reviewed_at": now,
            }
        )
        return True


class CodestraKyqraEntity(models.Model):
    _name = "codestra.kyqra.entity"
    _description = "Codestra Kyqra Extracted Entity"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"
    _rec_name = "name"

    batch_id = fields.Many2one(
        "codestra.kyqra.batch",
        required=True,
        index=True,
        readonly=True,
        ondelete="restrict",
        copy=False,
    )
    record_id = fields.Char(required=True, index=True, readonly=True, copy=False)
    name = fields.Char(required=True, index=True, readonly=True, copy=False)
    entity_type = fields.Char(required=True, readonly=True, copy=False)
    source_url = fields.Char(required=True, readonly=True, copy=False)
    data_json = fields.Json(required=True, readonly=True, copy=False)
    provenance_json = fields.Json(required=True, readonly=True, copy=False)
    confidence = fields.Float(required=True, readonly=True, copy=False)
    review_required = fields.Boolean(
        required=True,
        default=True,
        readonly=True,
        copy=False,
        tracking=True,
    )
    review_state = fields.Selection(
        [
            ("review_pending", "Review Pending"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        required=True,
        default="review_pending",
        index=True,
        readonly=True,
        copy=False,
        tracking=True,
    )
    reviewed_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    reviewed_at = fields.Datetime(readonly=True, copy=False)
    evidence_ids = fields.One2many(
        "codestra.kyqra.evidence",
        "entity_id",
        string="Evidence",
        readonly=True,
    )

    _batch_record_unique = models.Constraint(
        "UNIQUE(batch_id,record_id)",
        "A Kyqra record ID must be unique inside a batch.",
    )
    _confidence_range = models.Constraint(
        "CHECK(confidence >= 0 AND confidence <= 1)",
        "Kyqra confidence must be between zero and one.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not (
            self.env.context.get(INTERNAL_CONTEXT) is _INTERNAL_CAPABILITY
            and self.env.user.has_group(SERVICE_GROUP)
        ):
            raise AccessError(
                _("Kyqra entities can be created only by the governed service method.")
            )
        for values in vals_list:
            if values.get("review_required") is not True:
                raise ValidationError(_("Kyqra entities must remain review required."))
        return super().create(vals_list)

    def write(self, values):
        if not (
            self.env.context.get(INTERNAL_CONTEXT) is _INTERNAL_CAPABILITY
            and self.env.user.has_group(REVIEWER_GROUP)
        ):
            raise AccessError(_("Kyqra entity evidence is immutable."))
        allowed = {"review_state", "reviewed_by_id", "reviewed_at"}
        if set(values) - allowed:
            raise AccessError(_("Only governed review fields may change."))
        return super().write(values)

    def unlink(self):
        raise AccessError(_("Kyqra entities are retained and cannot be deleted."))

    def action_approve(self):
        if not self.env.user.has_group(REVIEWER_GROUP):
            raise AccessError(_("Kyqra review requires the reviewer group."))
        if any(entity.review_state != "review_pending" for entity in self):
            raise UserError(_("Only review-pending entities can be approved."))
        if any(entity.batch_id.state != "review_pending" for entity in self):
            raise UserError(_("The batch must remain review pending."))
        now = fields.Datetime.now()
        self.with_context(**{INTERNAL_CONTEXT: _INTERNAL_CAPABILITY}).write(
            {
                "review_state": "approved",
                "reviewed_by_id": self.env.user.id,
                "reviewed_at": now,
            }
        )
        return True

    def action_reject(self):
        if not self.env.user.has_group(REVIEWER_GROUP):
            raise AccessError(_("Kyqra review requires the reviewer group."))
        if any(entity.review_state != "review_pending" for entity in self):
            raise UserError(_("Only review-pending entities can be rejected."))
        if any(entity.batch_id.state != "review_pending" for entity in self):
            raise UserError(_("The batch must remain review pending."))
        now = fields.Datetime.now()
        self.with_context(**{INTERNAL_CONTEXT: _INTERNAL_CAPABILITY}).write(
            {
                "review_state": "rejected",
                "reviewed_by_id": self.env.user.id,
                "reviewed_at": now,
            }
        )
        return True


class CodestraKyqraEvidence(models.Model):
    _name = "codestra.kyqra.evidence"
    _description = "Codestra Kyqra Provenance Evidence"
    _order = "id"
    _rec_name = "source_url"

    entity_id = fields.Many2one(
        "codestra.kyqra.entity",
        required=True,
        index=True,
        readonly=True,
        ondelete="restrict",
        copy=False,
    )
    source_url = fields.Char(required=True, readonly=True, copy=False)
    capture_method = fields.Selection(
        [(value, value.title()) for value in sorted(ALLOWED_CAPTURE_METHODS)],
        required=True,
        readonly=True,
        copy=False,
    )
    content_digest = fields.Char(readonly=True, copy=False)
    locator = fields.Char(readonly=True, copy=False)
    quote = fields.Text(readonly=True, copy=False)
    captured_at = fields.Char(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if not (
            self.env.context.get(INTERNAL_CONTEXT) is _INTERNAL_CAPABILITY
            and self.env.user.has_group(SERVICE_GROUP)
        ):
            raise AccessError(
                _("Kyqra evidence can be created only by the governed service method.")
            )
        return super().create(vals_list)

    def write(self, values):
        raise AccessError(_("Kyqra provenance evidence is immutable."))

    def unlink(self):
        raise AccessError(
            _("Kyqra provenance evidence is retained and cannot be deleted.")
        )
