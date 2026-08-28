import csv
import hashlib
import io
import json
import re
import uuid
from pathlib import Path

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


CATALOG_COLUMNS = (
    "canonical_campaign_code",
    "vicidial_campaign_id",
    "business_unit_code",
    "direction",
    "technical_callback_compatibility",
    "agent_login_allowed",
    "vicidial_user_group_id",
    "vicidial_inbound_group_id",
    "default_list_id",
    "vicidial_script_id",
    "disposition_set_key",
    "email_alias_key",
    "catalog_status",
)
CATALOG_NORMALIZED_SHA256 = (
    "773d56967de1c8ba9791c84c06007094bd7a9847156ec9c9fc08d89d6600536a"
)
MAPPING_NAMESPACE = uuid.UUID("ecf2f3c6-418e-5e18-8cc9-8cb175dd0051")
MAPPING_WRITE_CAPABILITY = object()
READBACK_WRITE_CAPABILITY = object()
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
NATIVE_ID_PATTERN = re.compile(r"^[A-Z0-9]{1,8}$")
EVIDENCE_REFERENCE_PATTERN = re.compile(
    r"^(?:(?:staging|evidence)://|urn:)[A-Za-z0-9][A-Za-z0-9._:/-]{0,500}$"
)
OPTIONAL_CATALOG_FIELDS = (
    "vicidial_user_group_id",
    "vicidial_inbound_group_id",
    "default_list_id",
    "vicidial_script_id",
    "disposition_set_key",
    "email_alias_key",
)


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value):
    encoded = value if isinstance(value, bytes) else str(value).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _catalog_path():
    return Path(__file__).resolve().parent.parent / "data" / "campaign_identifiers.csv"


def _catalog_rows():
    raw = _catalog_path().read_bytes()
    normalized = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    if _sha256(normalized) != CATALOG_NORMALIZED_SHA256:
        raise ValidationError(_("The controlled campaign identifier catalog checksum changed."))
    reader = csv.DictReader(io.StringIO(normalized, newline=""))
    if tuple(reader.fieldnames or ()) != CATALOG_COLUMNS:
        raise ValidationError(_("The controlled campaign identifier catalog schema changed."))
    rows = list(reader)
    if len(rows) != 93:
        raise ValidationError(_("The controlled campaign identifier catalog must contain 93 rows."))
    return rows


def _catalog_bool(value, field_name):
    if value not in {"TRUE", "FALSE"}:
        raise ValidationError(_("Catalog field %(field)s must be TRUE or FALSE.", field=field_name))
    return value == "TRUE"


def _optional_catalog_value(value):
    return False if value == "MISSING" else value


class CcTelephonyMapping(models.Model):
    _name = "cc.telephony.mapping"
    _description = "Governed Canonical VICIdial Campaign Mapping"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "canonical_campaign_code"
    _rec_name = "canonical_campaign_code"
    _rec_names_search = ["canonical_campaign_code", "vicidial_campaign_id", "mapping_uuid"]

    channel_id = fields.Many2one(
        "cc.campaign.channel", required=True, ondelete="restrict", index=True, copy=False
    )
    mapping_uuid = fields.Char(required=True, size=36, index=True, copy=False, readonly=True)
    environment = fields.Selection(
        related="campaign_id.environment", store=True, readonly=True, index=True
    )
    business_unit_code = fields.Char(
        related="business_unit_id.code", store=True, readonly=True, index=True
    )
    canonical_campaign_code = fields.Char(
        related="channel_id.code", store=True, readonly=True, index=True
    )
    vicidial_campaign_id = fields.Char(required=True, size=8, index=True, copy=False, readonly=True)
    direction = fields.Selection(
        related="channel_id.direction", store=True, readonly=True, index=True
    )
    technical_callback_compatibility = fields.Boolean(
        related="channel_id.technical_callback_compatibility", store=True, readonly=True
    )
    agent_login_allowed = fields.Boolean(
        related="channel_id.agent_login_allowed", store=True, readonly=True
    )
    legacy_mapping_id = fields.Many2one(
        related="channel_id.legacy_mapping_id", store=True, readonly=True
    )
    legacy_vicidial_campaign_id = fields.Char(
        related="legacy_mapping_id.vicidial_campaign_id", store=True, readonly=True
    )
    vicidial_user_group_id = fields.Char(readonly=True, copy=False)
    vicidial_inbound_group_id = fields.Char(readonly=True, copy=False)
    default_list_id = fields.Char(readonly=True, copy=False)
    vicidial_script_id = fields.Char(readonly=True, copy=False)
    disposition_set_key = fields.Char(readonly=True, copy=False)
    email_alias_key = fields.Char(readonly=True, copy=False)
    middleware_scope = fields.Char(
        required=True,
        default="odoo.telephony.campaign-mapping",
        readonly=True,
        copy=False,
    )
    catalog_status = fields.Selection(
        [("partial", "Partial")], required=True, default="partial", readonly=True, copy=False
    )
    catalog_sha256 = fields.Char(required=True, size=64, readonly=True, copy=False)
    catalog_row_sha256 = fields.Char(required=True, size=64, readonly=True, copy=False)
    mapping_version = fields.Integer(required=True, default=1, readonly=True, copy=False)
    desired_external_state = fields.Selection(
        [("disabled", "Disabled")], required=True, default="disabled", readonly=True, copy=False
    )
    desired_enabled = fields.Boolean(required=True, default=False, readonly=True, copy=False)
    provisioning_enabled = fields.Boolean(required=True, default=False, readonly=True, copy=False)
    agent_sync_enabled = fields.Boolean(required=True, default=False, readonly=True, copy=False)
    live_call_control_enabled = fields.Boolean(required=True, default=False, readonly=True, copy=False)
    desired_state_hash = fields.Char(
        compute="_compute_desired_state_hash", store=True, readonly=True, size=64, index=True
    )
    legacy_classification = fields.Selection(
        [
            ("match", "Match"),
            ("drift", "Drift"),
            ("missing", "Missing"),
            ("conflict", "Conflict"),
        ],
        required=True,
        readonly=True,
        copy=False,
        index=True,
    )
    migration_state = fields.Selection(
        [
            ("blocked_partial_catalog", "Blocked: Partial Catalog"),
            ("blocked_conflict", "Blocked: Identifier Conflict"),
            ("ready_disabled", "Ready: Disabled Only"),
        ],
        required=True,
        default="blocked_partial_catalog",
        readonly=True,
        copy=False,
        index=True,
    )
    reconciliation_status = fields.Selection(
        [
            ("not_observed", "Not Observed"),
            ("match", "Match"),
            ("drift", "Drift"),
            ("missing", "Missing"),
            ("conflict", "Conflict"),
        ],
        required=True,
        default="not_observed",
        readonly=True,
        copy=False,
        index=True,
    )
    last_readback_id = fields.Many2one(
        "cc.telephony.readback", ondelete="restrict", readonly=True, copy=False
    )
    last_readback_at = fields.Datetime(readonly=True, copy=False)
    last_observed_vicidial_campaign_id = fields.Char(size=8, readonly=True, copy=False)
    last_observed_enabled = fields.Boolean(readonly=True, copy=False)

    _channel_unique = models.Constraint(
        "unique(channel_id)", "A campaign channel may have only one governed mapping."
    )
    _mapping_uuid_unique = models.Constraint(
        "unique(mapping_uuid)", "Governed telephony mapping UUIDs must be unique."
    )
    _canonical_environment_unique = models.Constraint(
        "unique(environment, canonical_campaign_code)",
        "Canonical campaign mapping codes must be unique per environment.",
    )
    _native_environment_unique = models.Constraint(
        "unique(environment, vicidial_campaign_id)",
        "VICIdial campaign IDs must be unique per environment.",
    )
    _mapping_version_positive = models.Constraint(
        "check(mapping_version > 0)", "Mapping versions must be positive."
    )

    def _desired_state_document(self):
        self.ensure_one()
        return {
            "schema_version": "1.0",
            "mapping_uuid": self.mapping_uuid,
            "mapping_version": self.mapping_version,
            "environment": self.environment,
            "business_unit_code": self.business_unit_code,
            "canonical_campaign_code": self.canonical_campaign_code,
            "vicidial_campaign_id": self.vicidial_campaign_id,
            "direction": self.direction,
            "technical_callback_compatibility": self.technical_callback_compatibility,
            "agent_login_allowed": self.agent_login_allowed,
            "vicidial_user_group_id": self.vicidial_user_group_id or None,
            "vicidial_inbound_group_id": self.vicidial_inbound_group_id or None,
            "default_list_id": self.default_list_id or None,
            "vicidial_script_id": self.vicidial_script_id or None,
            "disposition_set_key": self.disposition_set_key or None,
            "email_alias_key": self.email_alias_key or None,
            "desired_external_state": self.desired_external_state,
            "desired_enabled": self.desired_enabled,
            "provisioning_enabled": self.provisioning_enabled,
            "agent_sync_enabled": self.agent_sync_enabled,
            "live_call_control_enabled": self.live_call_control_enabled,
            "catalog_status": self.catalog_status,
            "catalog_row_sha256": self.catalog_row_sha256,
            "migration_state": self.migration_state,
        }

    @api.depends(
        "mapping_uuid",
        "mapping_version",
        "environment",
        "business_unit_code",
        "canonical_campaign_code",
        "vicidial_campaign_id",
        "direction",
        "technical_callback_compatibility",
        "agent_login_allowed",
        "vicidial_user_group_id",
        "vicidial_inbound_group_id",
        "default_list_id",
        "vicidial_script_id",
        "disposition_set_key",
        "email_alias_key",
        "desired_external_state",
        "desired_enabled",
        "provisioning_enabled",
        "agent_sync_enabled",
        "live_call_control_enabled",
        "catalog_status",
        "catalog_row_sha256",
        "migration_state",
    )
    def _compute_desired_state_hash(self):
        for mapping in self:
            mapping.desired_state_hash = _sha256(
                _canonical_json(mapping._desired_state_document())
            )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_telephony_mapping_write") is not MAPPING_WRITE_CAPABILITY:
            raise AccessError(_("Governed telephony mappings are loaded only from the controlled catalog."))
        return super().create(values_list)

    def write(self, values):
        if self.env.context.get("_cc_telephony_mapping_write") is not MAPPING_WRITE_CAPABILITY:
            raise AccessError(_("Governed telephony mappings cannot be edited directly."))
        return super().write(values)

    def unlink(self):
        raise AccessError(_("Governed telephony mappings are retained, not deleted."))

    def copy(self, default=None):
        raise AccessError(_("Governed telephony mappings cannot be copied."))

    def export_data(self, fields_to_export, raw_data=False):
        if not (
            self.env.user.has_group("codestra_cc_security.group_cc_global_administrator")
            or self.env.user.has_group("codestra_cc_security.group_cc_auditor")
        ):
            raise UserError(_("Telephony mapping export is restricted to administrators and auditors."))
        return super().export_data(fields_to_export, raw_data=raw_data)

    @api.constrains(
        "campaign_id",
        "channel_id",
        "mapping_uuid",
        "vicidial_campaign_id",
        "technical_callback_compatibility",
        "agent_login_allowed",
        "catalog_status",
        "catalog_sha256",
        "catalog_row_sha256",
        "desired_external_state",
        "desired_enabled",
        "provisioning_enabled",
        "agent_sync_enabled",
        "live_call_control_enabled",
        "migration_state",
    )
    def _check_mapping_contract(self):
        for mapping in self:
            if mapping.channel_id.campaign_id != mapping.campaign_id:
                raise ValidationError(_("Telephony channel and campaign scope must match."))
            if not NATIVE_ID_PATTERN.fullmatch(mapping.vicidial_campaign_id or ""):
                raise ValidationError(_("VICIdial campaign IDs require 1-8 uppercase letters or digits."))
            if not re.fullmatch(r"[0-9a-f-]{36}", mapping.mapping_uuid or ""):
                raise ValidationError(_("Telephony mapping UUID is invalid."))
            if mapping.technical_callback_compatibility and mapping.agent_login_allowed:
                raise ValidationError(_("Technical callback mappings cannot allow agent login."))
            if mapping.catalog_status != "partial" or mapping.migration_state not in {
                "blocked_partial_catalog",
                "blocked_conflict",
            }:
                raise ValidationError(_("Partial catalog mappings must remain migration-blocked."))
            if mapping.catalog_sha256 != CATALOG_NORMALIZED_SHA256:
                raise ValidationError(_("Telephony mapping catalog checksum is invalid."))
            if not SHA256_PATTERN.fullmatch(mapping.catalog_row_sha256 or ""):
                raise ValidationError(_("Telephony mapping row checksum is invalid."))
            if (
                mapping.desired_external_state != "disabled"
                or mapping.desired_enabled
                or mapping.provisioning_enabled
                or mapping.agent_sync_enabled
                or mapping.live_call_control_enabled
            ):
                raise ValidationError(_("Partial mappings cannot enable VICIdial operations."))

    @api.model
    def _load_controlled_catalog(self):
        if self.env.uid != SUPERUSER_ID:
            raise AccessError(_("Only module installation may load the controlled catalog."))
        rows = _catalog_rows()
        canonical_codes = [row["canonical_campaign_code"] for row in rows]
        native_ids = [row["vicidial_campaign_id"] for row in rows]
        if len(set(canonical_codes)) != 93 or len(set(native_ids)) != 93:
            raise ValidationError(_("Controlled campaign and VICIdial identifiers must be unique."))
        if any(not NATIVE_ID_PATTERN.fullmatch(value or "") for value in native_ids):
            raise ValidationError(_("The controlled catalog contains an invalid VICIdial ID."))

        Channel = self.env["cc.campaign.channel"].with_context(active_test=False)
        Legacy = self.env["call.center.campaign.mapping"].with_context(active_test=False)
        Governed = self.with_context(
            active_test=False, _cc_telephony_mapping_write=MAPPING_WRITE_CAPABILITY
        )
        for row in rows:
            code = row["canonical_campaign_code"]
            channel = Channel.search([("code", "=", code)])
            if len(channel) != 1:
                raise ValidationError(
                    _("Catalog code %(code)s must resolve to exactly one campaign channel.", code=code)
                )
            callback = _catalog_bool(
                row["technical_callback_compatibility"],
                "technical_callback_compatibility",
            )
            agent_login = _catalog_bool(row["agent_login_allowed"], "agent_login_allowed")
            expected_direction = "inbound" if row["direction"] == "IN" else "outbound"
            if row["direction"] not in {"IN", "OUT"}:
                raise ValidationError(_("Catalog direction must be IN or OUT."))
            if (
                channel.business_unit_id.code != row["business_unit_code"]
                or channel.direction != expected_direction
                or channel.technical_callback_compatibility != callback
                or channel.agent_login_allowed != agent_login
            ):
                raise ValidationError(_("Catalog scope disagrees with channel %(code)s.", code=code))
            if row["catalog_status"] != "PARTIAL" or any(
                row[field_name] != "MISSING" for field_name in OPTIONAL_CATALOG_FIELDS
            ):
                raise ValidationError(_("The controlled partial-catalog contract changed."))

            conflicting = Legacy.search(
                [
                    ("vicidial_campaign_id", "=", row["vicidial_campaign_id"]),
                    ("id", "!=", channel.legacy_mapping_id.id),
                ],
                limit=1,
            )
            if conflicting:
                classification = "conflict"
            elif not channel.legacy_mapping_id:
                classification = "missing"
            elif channel.legacy_mapping_id.vicidial_campaign_id == row["vicidial_campaign_id"]:
                classification = "match"
            else:
                classification = "drift"
            migration_state = (
                "blocked_conflict" if classification == "conflict" else "blocked_partial_catalog"
            )
            mapping_uuid = str(
                uuid.uuid5(MAPPING_NAMESPACE, f"{channel.campaign_id.environment}:{code}")
            )
            row_hash = _sha256(_canonical_json({field: row[field] for field in CATALOG_COLUMNS}))
            values = {
                "campaign_id": channel.campaign_id.id,
                "channel_id": channel.id,
                "mapping_uuid": mapping_uuid,
                "vicidial_campaign_id": row["vicidial_campaign_id"],
                **{
                    field_name: _optional_catalog_value(row[field_name])
                    for field_name in OPTIONAL_CATALOG_FIELDS
                },
                "catalog_status": "partial",
                "catalog_sha256": CATALOG_NORMALIZED_SHA256,
                "catalog_row_sha256": row_hash,
                "legacy_classification": classification,
                "migration_state": migration_state,
            }
            existing = Governed.search([("channel_id", "=", channel.id)], limit=1)
            if existing:
                immutable = {
                    field_name: values[field_name]
                    for field_name in values
                    if field_name not in {"legacy_classification", "migration_state"}
                }
                changed = False
                for field_name, value in immutable.items():
                    current = existing[field_name]
                    if existing._fields[field_name].type == "many2one":
                        current = current.id
                    if current != value:
                        changed = True
                        break
                if changed:
                    raise ValidationError(
                        _("Controlled mapping identity changed for %(code)s; use an approved migration.", code=code)
                    )
                if (
                    existing.legacy_classification != classification
                    or existing.migration_state != migration_state
                ):
                    existing.write(
                        {
                            "legacy_classification": classification,
                            "migration_state": migration_state,
                        }
                    )
            else:
                Governed.create(values)
        if Governed.search_count([]) != 93:
            raise ValidationError(_("Governed catalog load must result in exactly 93 mappings."))
        return {
            "catalog_rows": 93,
            "catalog_sha256": CATALOG_NORMALIZED_SHA256,
            "mappings": Governed.search_count([]),
        }

    def action_record_readback(
        self,
        event_id,
        observed_vicidial_campaign_id,
        observed_exists,
        observed_enabled,
        observed_payload_hash,
        evidence_reference,
        source_system="codestra-middleware",
    ):
        self.ensure_one()
        if not self.env.user.has_group(
            "codestra_cc_vicidial.group_cc_telephony_readback_service"
        ):
            raise AccessError(_("Only the governed middleware service may record telephony read-back."))
        event_id = str(event_id or "").strip()
        native_id = str(observed_vicidial_campaign_id or "").strip().upper()
        payload_hash = str(observed_payload_hash or "").removeprefix("sha256:").lower()
        evidence_reference = str(evidence_reference or "").strip()
        source_system = str(source_system or "").strip()
        if not event_id or len(event_id) > 128 or not re.fullmatch(r"[A-Za-z0-9._:-]+", event_id):
            raise ValidationError(_("Read-back event identifiers are invalid."))
        if native_id and not NATIVE_ID_PATTERN.fullmatch(native_id):
            raise ValidationError(_("Observed VICIdial campaign IDs are invalid."))
        if not SHA256_PATTERN.fullmatch(payload_hash):
            raise ValidationError(_("Read-back payload hash must be SHA-256."))
        if not EVIDENCE_REFERENCE_PATTERN.fullmatch(evidence_reference):
            raise ValidationError(_("Read-back evidence must use a safe retained-evidence reference."))
        if not source_system or len(source_system) > 64 or not re.fullmatch(
            r"[A-Za-z0-9._-]+", source_system
        ):
            raise ValidationError(_("Read-back source system is invalid."))

        Readback = self.env["cc.telephony.readback"].with_context(
            _cc_telephony_readback_write=READBACK_WRITE_CAPABILITY
        )
        fingerprint = _sha256(
            _canonical_json(
                {
                    "mapping_uuid": self.mapping_uuid,
                    "event_id": event_id,
                    "observed_vicidial_campaign_id": native_id or None,
                    "observed_exists": bool(observed_exists),
                    "observed_enabled": bool(observed_enabled),
                    "observed_payload_hash": payload_hash,
                    "evidence_reference": evidence_reference,
                    "source_system": source_system,
                }
            )
        )
        existing = Readback.search([("event_id", "=", event_id)], limit=1)
        if existing:
            if existing.event_fingerprint != fingerprint:
                raise ValidationError(_("Altered telephony read-back replay was rejected."))
            return existing
        if not observed_exists:
            result = "missing"
        elif native_id != self.vicidial_campaign_id:
            result = "conflict"
        elif observed_enabled:
            result = "drift"
        else:
            result = "match"
        readback = Readback.create(
            {
                "mapping_id": self.id,
                "campaign_id": self.campaign_id.id,
                "event_id": event_id,
                "event_fingerprint": fingerprint,
                "source_system": source_system,
                "observed_vicidial_campaign_id": native_id or False,
                "observed_exists": bool(observed_exists),
                "observed_enabled": bool(observed_enabled),
                "observed_payload_hash": payload_hash,
                "evidence_reference": evidence_reference,
                "result": result,
                "recorded_at": fields.Datetime.now(),
            }
        )
        self.with_context(_cc_telephony_mapping_write=MAPPING_WRITE_CAPABILITY).write(
            {
                "last_readback_id": readback.id,
                "last_readback_at": readback.recorded_at,
                "last_observed_vicidial_campaign_id": native_id or False,
                "last_observed_enabled": bool(observed_enabled),
                "reconciliation_status": result,
            }
        )
        return readback


class CcTelephonyReadback(models.Model):
    _name = "cc.telephony.readback"
    _description = "Immutable VICIdial Mapping Read-back Evidence"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "recorded_at desc, id desc"
    _rec_name = "event_id"

    mapping_id = fields.Many2one(
        "cc.telephony.mapping", required=True, ondelete="restrict", index=True, copy=False
    )
    event_id = fields.Char(required=True, size=128, index=True, readonly=True, copy=False)
    event_fingerprint = fields.Char(required=True, size=64, readonly=True, copy=False)
    source_system = fields.Char(required=True, size=64, readonly=True, copy=False)
    observed_vicidial_campaign_id = fields.Char(size=8, readonly=True, copy=False)
    observed_exists = fields.Boolean(required=True, readonly=True, copy=False)
    observed_enabled = fields.Boolean(required=True, readonly=True, copy=False)
    observed_payload_hash = fields.Char(required=True, size=64, readonly=True, copy=False)
    evidence_reference = fields.Char(required=True, size=512, readonly=True, copy=False)
    result = fields.Selection(
        [
            ("match", "Match"),
            ("drift", "Drift"),
            ("missing", "Missing"),
            ("conflict", "Conflict"),
        ],
        required=True,
        readonly=True,
        copy=False,
        index=True,
    )
    recorded_at = fields.Datetime(required=True, readonly=True, copy=False, index=True)

    _event_id_unique = models.Constraint(
        "unique(event_id)", "Telephony read-back event IDs must be globally unique."
    )
    _event_fingerprint_unique = models.Constraint(
        "unique(event_fingerprint)", "Telephony read-back event fingerprints must be unique."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_telephony_readback_write") is not READBACK_WRITE_CAPABILITY:
            raise AccessError(_("Telephony read-back evidence requires the governed service path."))
        return super().create(values_list)

    def write(self, values):
        raise AccessError(_("Telephony read-back evidence is immutable."))

    def unlink(self):
        raise AccessError(_("Telephony read-back evidence is retained, not deleted."))

    def copy(self, default=None):
        raise AccessError(_("Telephony read-back evidence cannot be copied."))

    def export_data(self, fields_to_export, raw_data=False):
        if not (
            self.env.user.has_group("codestra_cc_security.group_cc_global_administrator")
            or self.env.user.has_group("codestra_cc_security.group_cc_auditor")
        ):
            raise UserError(_("Telephony evidence export is restricted to administrators and auditors."))
        return super().export_data(fields_to_export, raw_data=raw_data)

    @api.constrains(
        "mapping_id",
        "campaign_id",
        "event_fingerprint",
        "observed_vicidial_campaign_id",
        "observed_payload_hash",
        "evidence_reference",
    )
    def _check_readback_contract(self):
        for readback in self:
            if readback.mapping_id.campaign_id != readback.campaign_id:
                raise ValidationError(_("Telephony read-back campaign scope must match its mapping."))
            if not SHA256_PATTERN.fullmatch(readback.event_fingerprint or ""):
                raise ValidationError(_("Telephony event fingerprint must be SHA-256."))
            if not SHA256_PATTERN.fullmatch(readback.observed_payload_hash or ""):
                raise ValidationError(_("Telephony observed payload hash must be SHA-256."))
            if readback.observed_vicidial_campaign_id and not NATIVE_ID_PATTERN.fullmatch(
                readback.observed_vicidial_campaign_id
            ):
                raise ValidationError(_("Observed VICIdial campaign ID is invalid."))
            if not EVIDENCE_REFERENCE_PATTERN.fullmatch(readback.evidence_reference or ""):
                raise ValidationError(_("Telephony evidence reference is invalid."))


class CcTelephonyMiddlewareContract(models.AbstractModel):
    _name = "cc.telephony.middleware.contract"
    _description = "Middleware-only VICIdial Campaign Mapping Contract"

    @api.model
    def get_desired_state(self, mapping_uuid):
        mapping = self.env["cc.telephony.mapping"].search(
            [("mapping_uuid", "=", str(mapping_uuid or ""))], limit=1
        )
        if not mapping:
            raise ValidationError(_("Governed telephony mapping was not found."))
        mapping.check_access("read")
        document = mapping._desired_state_document()
        document["desired_state_hash"] = f"sha256:{mapping.desired_state_hash}"
        return document

    @api.model
    def accept_readback(self, mapping_uuid, readback):
        mapping = self.env["cc.telephony.mapping"].search(
            [("mapping_uuid", "=", str(mapping_uuid or ""))], limit=1
        )
        if not mapping:
            raise ValidationError(_("Governed telephony mapping was not found."))
        if not isinstance(readback, dict):
            raise ValidationError(_("Telephony read-back must be a key/value document."))
        allowed = {
            "event_id",
            "observed_vicidial_campaign_id",
            "observed_exists",
            "observed_enabled",
            "observed_payload_hash",
            "evidence_reference",
            "source_system",
        }
        if set(readback).difference(allowed):
            raise ValidationError(_("Telephony read-back contains unsupported fields."))
        required = allowed.difference({"source_system"})
        if not required.issubset(readback):
            raise ValidationError(_("Telephony read-back is missing required fields."))
        return mapping.action_record_readback(**readback)
