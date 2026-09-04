from __future__ import annotations

import hashlib
import json
import uuid
from urllib.parse import urlsplit

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


MAX_PAYLOAD_BYTES = 131_072
PROJECTION_RESULTS = ("created", "updated", "stale_ignored", "unchanged")
PROJECTION_STATUSES = {"projected", "review_required", "suppressed"}


class CodestraScrapperBusiness(models.Model):
    _name = "codestra.scrapper.business"
    _description = "Codestra Scrapper Business Projection"
    _order = "last_projected_at desc, id desc"
    _rec_name = "company_name"

    tenant_id = fields.Char(required=True, index=True, readonly=True, copy=False)
    external_business_id = fields.Char(
        required=True, index=True, readonly=True, copy=False
    )
    external_version = fields.Integer(
        required=True, default=1, index=True, readonly=True, copy=False
    )
    company_name = fields.Char(required=True, index=True)
    website = fields.Char(index=True)
    email = fields.Char(index=True)
    phone = fields.Char(index=True)
    country_code = fields.Char(size=2, index=True)
    source_url = fields.Char(readonly=True, copy=False)
    source_captured_at = fields.Datetime(readonly=True, copy=False)
    adapter_version = fields.Char(readonly=True, copy=False)
    mapping_version = fields.Char(
        required=True, default="1.0", readonly=True, copy=False
    )
    evidence_summary = fields.Json(readonly=True, copy=False)
    confidence = fields.Float(readonly=True, copy=False)
    last_event_id = fields.Char(required=True, index=True, readonly=True, copy=False)
    last_correlation_id = fields.Char(index=True, readonly=True, copy=False)
    last_projection_digest = fields.Char(
        required=True, index=True, readonly=True, copy=False
    )
    last_projected_at = fields.Datetime(
        required=True,
        default=fields.Datetime.now,
        index=True,
        readonly=True,
        copy=False,
    )
    projection_status = fields.Selection(
        [
            ("projected", "Projected"),
            ("review_required", "Review required"),
            ("suppressed", "Suppressed"),
        ],
        required=True,
        default="projected",
        index=True,
        readonly=True,
        copy=False,
    )
    reconciliation_status = fields.Selection(
        [
            ("in_sync", "In sync"),
            ("drift_detected", "Drift detected"),
            ("reconciliation_required", "Reconciliation required"),
        ],
        required=True,
        default="in_sync",
        index=True,
        readonly=True,
        copy=False,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Contact",
        ondelete="set null",
        index=True,
        readonly=True,
        copy=False,
    )
    active = fields.Boolean(default=True, index=True)

    _tenant_business_unique = models.Constraint(
        "unique(tenant_id, external_business_id)",
        "The Scrapper business ID must be unique inside a tenant.",
    )
    _external_version_positive = models.Constraint(
        "CHECK(external_version > 0)",
        "The Scrapper business version must be positive.",
    )
    _confidence_range = models.Constraint(
        "CHECK(confidence >= 0 AND confidence <= 1)",
        "Projection confidence must be between zero and one.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("codestra_scrapper_projection_internal"):
            raise AccessError(
                _("Scrapper projections can be created only by the governed service method.")
            )
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get("codestra_scrapper_projection_internal"):
            raise AccessError(
                _("Scrapper projections can be updated only by the governed service method.")
            )
        result = super().write(vals)
        self._assert_no_committed_version_regression()
        return result

    def unlink(self):
        raise AccessError(
            _("Scrapper projections are retained for audit and cannot be deleted.")
        )

    def _assert_no_committed_version_regression(self):
        receipt_model = self.env["codestra.scrapper.projection.receipt"].sudo()
        for projection in self:
            latest = receipt_model.search(
                [
                    ("tenant_id", "=", projection.tenant_id),
                    ("business_id", "=", projection.external_business_id),
                    ("result", "in", PROJECTION_RESULTS),
                ],
                order="incoming_version desc, id desc",
                limit=1,
            )
            if latest and projection.external_version < latest.incoming_version:
                raise ValidationError(
                    _(
                        "A newer committed Scrapper business version already exists; "
                        "the projection cannot regress."
                    )
                )

    @api.model
    def apply_middleware_projection(self, payload):
        """Apply one normalized, policy-approved Middleware projection."""
        normalized, event_digest, projection_digest = self._normalize_payload(payload)
        tenant_id = normalized["tenant_id"]
        self._assert_service_authority(tenant_id)

        receipt_model = self.env["codestra.scrapper.projection.receipt"].sudo()
        prior = receipt_model.search(
            [
                ("tenant_id", "=", tenant_id),
                ("event_id", "=", normalized["event_id"]),
            ],
            limit=1,
        )
        if prior:
            if prior.payload_digest != event_digest:
                raise ValidationError(
                    _("event_id was already used with different content.")
                )
            return prior.as_receipt(duplicate=True)

        projection_model = self.sudo()
        projection = projection_model.search(
            [
                ("tenant_id", "=", tenant_id),
                ("external_business_id", "=", normalized["business_id"]),
            ],
            limit=1,
        )
        if (
            projection
            and normalized["version"] == projection.external_version
            and projection_digest != projection.last_projection_digest
        ):
            raise ValidationError(
                _(
                    "The incoming content conflicts with the existing content for "
                    "the same business version."
                )
            )

        receipt = self._reserve_event_receipt(
            receipt_model, normalized, event_digest
        )
        if receipt.result != "reserved":
            return receipt.as_receipt(duplicate=True)

        projection, result, message = self._apply_normalized_projection(
            projection, normalized, projection_digest
        )
        receipt.with_context(codestra_scrapper_projection_internal=True).write(
            {
                "projection_id": projection.id if projection else False,
                "result": result,
                "message": message,
            }
        )
        return receipt.as_receipt()

    @api.model
    def _reserve_event_receipt(self, receipt_model, normalized, event_digest):
        domain = [
            ("tenant_id", "=", normalized["tenant_id"]),
            ("event_id", "=", normalized["event_id"]),
        ]
        try:
            with self.env.cr.savepoint():
                receipt = receipt_model.with_context(
                    codestra_scrapper_projection_internal=True
                ).create(
                    {
                        "tenant_id": normalized["tenant_id"],
                        "event_id": normalized["event_id"],
                        "correlation_id": normalized["correlation_id"],
                        "business_id": normalized["business_id"],
                        "incoming_version": normalized["version"],
                        "result": "reserved",
                        "payload_digest": event_digest,
                    }
                )
                self.env.cr.flush()
                return receipt
        except Exception as exc:
            if getattr(exc, "pgcode", None) != "23505":
                raise
        receipt = receipt_model.search(domain, limit=1)
        if not receipt:
            raise ValidationError(_("Concurrent event reservation could not be resolved."))
        if receipt.payload_digest != event_digest:
            raise ValidationError(_("event_id was concurrently reused with different content."))
        return receipt

    @api.model
    def _apply_normalized_projection(self, projection, normalized, projection_digest):
        version = normalized["version"]
        if projection and version < projection.external_version:
            return (
                projection,
                "stale_ignored",
                "The incoming version is older than the current projection.",
            )
        if projection and version == projection.external_version:
            if projection_digest != projection.last_projection_digest:
                raise ValidationError(
                    _(
                        "The incoming content conflicts with the existing content "
                        "for the same business version."
                    )
                )
            return projection, "unchanged", False

        values = self._projection_values(normalized, projection_digest)
        partner_values = self._partner_values(normalized)
        if projection:
            partner = projection.partner_id.sudo()
            if partner:
                partner.write(partner_values)
            else:
                partner = self.env["res.partner"].sudo().create(partner_values)
            values["partner_id"] = partner.id
            projection.with_context(codestra_scrapper_projection_internal=True).write(
                values
            )
            return projection, "updated", False

        try:
            with self.env.cr.savepoint():
                partner = self.env["res.partner"].sudo().create(partner_values)
                values["partner_id"] = partner.id
                projection = self.sudo().with_context(
                    codestra_scrapper_projection_internal=True
                ).create(values)
                self.env.cr.flush()
                return projection, "created", False
        except Exception as exc:
            if getattr(exc, "pgcode", None) != "23505":
                raise

        projection = self.sudo().search(
            [
                ("tenant_id", "=", normalized["tenant_id"]),
                ("external_business_id", "=", normalized["business_id"]),
            ],
            limit=1,
        )
        if not projection:
            raise ValidationError(
                _("Concurrent business projection creation could not be resolved.")
            )
        return self._apply_normalized_projection(
            projection, normalized, projection_digest
        )

    @api.model
    def _assert_service_authority(self, tenant_id):
        if not self.env.user.has_group(
            "codestra_scrapper_projection.group_scrapper_projection_service"
        ):
            raise AccessError(
                _("Scrapper projection requires the dedicated Middleware service group.")
            )
        params = self.env["ir.config_parameter"].sudo()
        allowed = {
            item.strip().lower()
            for item in (params.get_param("codestra.scrapper.tenant_ids") or "").split(",")
            if item.strip()
        }
        if tenant_id not in allowed:
            raise AccessError(
                _("The Scrapper projection tenant is not authorized.")
            )
        binding_key = (
            f"codestra.middleware.tenant.{tenant_id}."
            "codestra.scrapper.service_user_id"
        )
        try:
            service_user_id = int(params.get_param(binding_key, "0"))
        except (TypeError, ValueError):
            service_user_id = 0
        if service_user_id != self.env.user.id:
            raise AccessError(
                _("The Scrapper tenant is not bound to this service principal.")
            )

    @api.model
    def _normalize_payload(self, payload):
        if not isinstance(payload, dict):
            raise ValidationError(_("The Scrapper projection payload must be an object."))
        encoded = self._canonical_json(payload)
        if len(encoded) > MAX_PAYLOAD_BYTES:
            raise ValidationError(
                _("The Scrapper projection payload exceeds 131072 bytes.")
            )
        event_digest = hashlib.sha256(encoded).hexdigest()

        normalized = {
            "tenant_id": self._canonical_uuid(payload.get("tenant_id"), "tenant_id"),
            "business_id": self._canonical_uuid(
                payload.get("business_id"), "business_id"
            ),
            "event_id": self._canonical_uuid(payload.get("event_id"), "event_id"),
            "correlation_id": self._canonical_uuid(
                payload.get("correlation_id"), "correlation_id"
            ),
            "version": self._positive_integer(payload.get("version"), "version"),
            "company_name": self._required_text(
                payload.get("company_name"), "company_name", 300
            ),
            "website": self._optional_url(payload.get("website"), "website"),
            "email": self._optional_text(payload.get("email"), "email", 320),
            "phone": self._optional_text(payload.get("phone"), "phone", 80),
            "country_code": self._country_code(payload.get("country_code")),
            "source_url": self._optional_url(
                payload.get("source_url"), "source_url"
            ),
            "source_captured_at": self._optional_datetime(
                payload.get("source_captured_at")
            ),
            "adapter_version": self._optional_text(
                payload.get("adapter_version"), "adapter_version", 80
            ),
            "mapping_version": self._optional_text(
                payload.get("mapping_version") or "1.0", "mapping_version", 80
            ),
            "evidence_summary": self._object(
                payload.get("evidence_summary") or {}, "evidence_summary"
            ),
            "confidence": self._confidence(payload.get("confidence", 0.0)),
            "projection_status": self._projection_status(
                payload.get("projection_status") or "projected"
            ),
        }
        projection_state = {
            key: normalized[key]
            for key in (
                "tenant_id",
                "business_id",
                "version",
                "company_name",
                "website",
                "email",
                "phone",
                "country_code",
                "source_url",
                "source_captured_at",
                "adapter_version",
                "mapping_version",
                "evidence_summary",
                "confidence",
                "projection_status",
            )
        }
        projection_digest = hashlib.sha256(
            self._canonical_json(projection_state)
        ).hexdigest()
        return normalized, event_digest, projection_digest

    @api.model
    def _projection_values(self, normalized, projection_digest):
        return {
            "tenant_id": normalized["tenant_id"],
            "external_business_id": normalized["business_id"],
            "external_version": normalized["version"],
            "company_name": normalized["company_name"],
            "website": normalized["website"],
            "email": normalized["email"],
            "phone": normalized["phone"],
            "country_code": normalized["country_code"],
            "source_url": normalized["source_url"],
            "source_captured_at": normalized["source_captured_at"],
            "adapter_version": normalized["adapter_version"],
            "mapping_version": normalized["mapping_version"],
            "evidence_summary": normalized["evidence_summary"],
            "confidence": normalized["confidence"],
            "last_event_id": normalized["event_id"],
            "last_correlation_id": normalized["correlation_id"],
            "last_projection_digest": projection_digest,
            "last_projected_at": fields.Datetime.now(),
            "projection_status": normalized["projection_status"],
            "reconciliation_status": "in_sync",
            "active": True,
        }

    @api.model
    def _partner_values(self, normalized):
        return {
            "name": normalized["company_name"],
            "website": normalized["website"],
            "email": normalized["email"],
            "phone": normalized["phone"],
            "company_type": "company",
        }

    @api.model
    def _canonical_json(self, value):
        try:
            return json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValidationError(
                _("The Scrapper projection payload must be JSON serializable.")
            ) from exc

    @api.model
    def _canonical_uuid(self, value, field_name):
        text = str(value or "").strip().lower()
        try:
            parsed = uuid.UUID(text)
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValidationError(_("%s must be a canonical UUID.") % field_name) from exc
        if not text or str(parsed) != text or parsed.int == 0:
            raise ValidationError(_("%s must be a canonical non-zero UUID.") % field_name)
        return text

    @api.model
    def _positive_integer(self, value, field_name):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValidationError(_("%s must be a positive integer.") % field_name)
        return value

    @api.model
    def _required_text(self, value, field_name, maximum):
        text = str(value or "").strip()
        if not text:
            raise ValidationError(_("%s is required.") % field_name)
        if len(text) > maximum:
            raise ValidationError(_("%s exceeds its maximum length.") % field_name)
        return text

    @api.model
    def _optional_text(self, value, field_name, maximum):
        if value in (None, False, ""):
            return False
        if not isinstance(value, str):
            raise ValidationError(_("%s must be a string.") % field_name)
        text = value.strip()
        if not text:
            return False
        if len(text) > maximum:
            raise ValidationError(_("%s exceeds its maximum length.") % field_name)
        return text

    @api.model
    def _optional_url(self, value, field_name):
        text = self._optional_text(value, field_name, 2048)
        if not text:
            return False
        parsed = urlsplit(text)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValidationError(
                _("%s must be an HTTP(S) URL without embedded credentials.") % field_name
            )
        return text

    @api.model
    def _optional_datetime(self, value):
        if value in (None, False, ""):
            return False
        try:
            parsed = fields.Datetime.to_datetime(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(_("source_captured_at must be a valid datetime.")) from exc
        if not parsed:
            raise ValidationError(_("source_captured_at must be a valid datetime."))
        return fields.Datetime.to_string(parsed)

    @api.model
    def _country_code(self, value):
        if value in (None, False, ""):
            return False
        if not isinstance(value, str):
            raise ValidationError(_("country_code must be a string."))
        text = value.strip().upper()
        if len(text) != 2 or not text.isalpha() or not text.isascii():
            raise ValidationError(_("country_code must be a two-letter ASCII code."))
        return text

    @api.model
    def _object(self, value, field_name):
        if not isinstance(value, dict):
            raise ValidationError(_("%s must be an object.") % field_name)
        return value

    @api.model
    def _confidence(self, value):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValidationError(_("confidence must be a number between zero and one."))
        number = float(value)
        if number < 0 or number > 1:
            raise ValidationError(_("confidence must be between zero and one."))
        return number

    @api.model
    def _projection_status(self, value):
        if value not in PROJECTION_STATUSES:
            raise ValidationError(_("projection_status is not supported."))
        return value


class CodestraScrapperProjectionReceipt(models.Model):
    _name = "codestra.scrapper.projection.receipt"
    _description = "Codestra Scrapper Projection Receipt"
    _order = "created_at desc, id desc"
    _rec_name = "event_id"

    tenant_id = fields.Char(required=True, index=True, readonly=True, copy=False)
    event_id = fields.Char(required=True, index=True, readonly=True, copy=False)
    correlation_id = fields.Char(required=True, index=True, readonly=True, copy=False)
    business_id = fields.Char(required=True, index=True, readonly=True, copy=False)
    projection_id = fields.Many2one(
        "codestra.scrapper.business",
        ondelete="set null",
        index=True,
        readonly=True,
        copy=False,
    )
    incoming_version = fields.Integer(required=True, readonly=True, copy=False)
    result = fields.Selection(
        [
            ("reserved", "Reserved"),
            ("created", "Created"),
            ("updated", "Updated"),
            ("stale_ignored", "Stale version ignored"),
            ("unchanged", "Unchanged"),
        ],
        required=True,
        default="reserved",
        index=True,
        readonly=True,
        copy=False,
    )
    payload_digest = fields.Char(required=True, index=True, readonly=True, copy=False)
    message = fields.Char(readonly=True, copy=False)
    created_at = fields.Datetime(
        required=True,
        default=fields.Datetime.now,
        index=True,
        readonly=True,
        copy=False,
    )

    _tenant_event_unique = models.Constraint(
        "unique(tenant_id, event_id)",
        "A projection receipt already exists for this tenant and event.",
    )
    _incoming_version_positive = models.Constraint(
        "CHECK(incoming_version > 0)",
        "The incoming Scrapper business version must be positive.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("codestra_scrapper_projection_internal"):
            raise AccessError(
                _("Projection receipts can be created only by the governed service method.")
            )
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get("codestra_scrapper_projection_internal"):
            raise AccessError(_("Projection receipts are immutable."))
        allowed = {"projection_id", "result", "message"}
        if set(vals) - allowed or any(receipt.result != "reserved" for receipt in self):
            raise AccessError(_("Finalized projection receipts are immutable."))
        return super().write(vals)

    def unlink(self):
        raise AccessError(_("Projection receipts are immutable."))

    def as_receipt(self, duplicate=False):
        self.ensure_one()
        return {
            "tenant_id": self.tenant_id,
            "event_id": self.event_id,
            "correlation_id": self.correlation_id,
            "business_id": self.business_id,
            "projection_id": self.projection_id.id or None,
            "incoming_version": self.incoming_version,
            "result": self.result,
            "payload_digest": self.payload_digest,
            "message": self.message or None,
            "created_at": fields.Datetime.to_string(self.created_at),
            "duplicate": bool(duplicate),
        }
