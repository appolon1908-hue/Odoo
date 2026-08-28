import hashlib
import json
import uuid

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


SENSITIVE_KEYS = {"authorization", "cookie", "password", "secret", "token", "api_key"}
ALLOWED_RECORD_TYPES = {"agent", "call", "campaign", "lead"}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class ConnectorNormalizer(models.AbstractModel):
    _name = "codestra.vicidial.connector.normalizer"
    _description = "Offline VICIdial record normalizer"

    @api.model
    def normalize(self, record_type, payload):
        if record_type not in ALLOWED_RECORD_TYPES:
            raise ValidationError("Unsupported connector record type.")
        if not isinstance(payload, dict):
            raise ValidationError("Connector payload must be an object.")
        clean = {}
        for key, value in payload.items():
            lowered = str(key).lower()
            if lowered in SENSITIVE_KEYS or any(marker in lowered for marker in ("password", "secret", "token")):
                continue
            clean[str(key)] = value
        return clean


class ConnectorProfile(models.Model):
    _name = "codestra.vicidial.connector.profile"
    _description = "VICIdial connector profile reference"
    _order = "name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=False)
    test_only = fields.Boolean(default=True, required=True)
    adapter_type = fields.Selection([("test_syn", "Synthetic test adapter")], default="test_syn", required=True)
    endpoint_reference = fields.Char(help="Configuration reference only; never a credential or endpoint secret.")
    credential_reference = fields.Char(help="External secret-manager reference only; no credential value is stored.")

    @api.constrains("active", "test_only", "adapter_type")
    def _check_fail_closed(self):
        for record in self:
            if record.active or not record.test_only or record.adapter_type != "test_syn":
                raise ValidationError("Only inactive TEST_SYN connector profiles are permitted.")


class ConnectorImportBatch(models.Model):
    _name = "codestra.vicidial.connector.import.batch"
    _description = "Offline VICIdial import preview batch"
    _order = "create_date desc"

    name = fields.Char(required=True, default=lambda self: str(uuid.uuid4()), readonly=True)
    profile_id = fields.Many2one("codestra.vicidial.connector.profile", required=True, ondelete="restrict")
    correlation_id = fields.Char(required=True, default=lambda self: str(uuid.uuid4()), index=True, readonly=True)
    source_fingerprint = fields.Char(index=True, readonly=True, copy=False)
    state = fields.Selection(
        [("draft", "Draft"), ("previewed", "Previewed"), ("validated", "Validated"), ("rejected", "Rejected")],
        default="draft", required=True, index=True, readonly=True,
    )
    line_ids = fields.One2many("codestra.vicidial.connector.import.line", "batch_id", readonly=True)
    record_count = fields.Integer(compute="_compute_record_count")

    _correlation_id_unique = models.Constraint(
        "UNIQUE(correlation_id)", "Connector correlation ID must be unique."
    )

    @api.depends("line_ids")
    def _compute_record_count(self):
        for record in self:
            record.record_count = len(record.line_ids)

    def preview(self, records):
        self.ensure_one()
        if self.state != "draft" or self.profile_id.active or not self.profile_id.test_only:
            raise ValidationError("Only a draft batch with an inactive test profile can be previewed.")
        if not isinstance(records, list):
            raise ValidationError("Preview records must be a list.")
        normalizer = self.env["codestra.vicidial.connector.normalizer"]
        lines = []
        normalized_records = []
        for item in records:
            if not isinstance(item, dict):
                raise ValidationError("Every preview item must be an object.")
            record_type = item.get("record_type")
            external_reference = str(item.get("external_reference") or "").strip()
            if not external_reference:
                raise ValidationError("Every preview item requires an external reference.")
            normalized = normalizer.normalize(record_type, item.get("payload", {}))
            serialized = _canonical(normalized)
            normalized_records.append({"record_type": record_type, "external_reference": external_reference, "payload": normalized})
            lines.append((0, 0, {
                "record_type": record_type,
                "external_reference": external_reference,
                "normalized_json": serialized,
                "payload_hash": hashlib.sha256(serialized.encode()).hexdigest(),
            }))
        fingerprint = hashlib.sha256(_canonical(normalized_records).encode()).hexdigest()
        self.write({"line_ids": lines, "source_fingerprint": fingerprint, "state": "previewed"})
        return self

    def validate_preview(self):
        for record in self:
            if record.state != "previewed" or not record.line_ids:
                raise ValidationError("Only a non-empty preview can be validated.")
            record.write({"state": "validated"})
        return True

    def apply_import(self):
        raise AccessError("Live VICIdial import is not implemented or enabled.")


class ConnectorImportLine(models.Model):
    _name = "codestra.vicidial.connector.import.line"
    _description = "Normalized VICIdial import preview line"
    _order = "id"

    batch_id = fields.Many2one("codestra.vicidial.connector.import.batch", required=True, ondelete="cascade", index=True)
    record_type = fields.Selection([(name, name.title()) for name in sorted(ALLOWED_RECORD_TYPES)], required=True, index=True)
    external_reference = fields.Char(required=True, index=True)
    normalized_json = fields.Text(required=True, readonly=True)
    payload_hash = fields.Char(required=True, readonly=True, index=True)

    _batch_external_reference_unique = models.Constraint(
        "UNIQUE(batch_id, record_type, external_reference)",
        "Preview references must be unique per batch and type.",
    )
