import json
import re
from datetime import timedelta

import requests
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FORMATS = (("mp3", "MP3"), ("wav", "WAV"), ("gsm", "GSM"))
RETENTION_CLASSES = (
    ("synthetic_test", "Synthetic test (7 days)"),
    ("standard", "Standard (365 days)"),
    ("high_compliance", "High compliance (1825 days)"),
    ("legal_hold", "Legal hold (indefinite)"),
)
RETENTION_DAYS = {"synthetic_test": 7, "standard": 365, "high_compliance": 1825}


class VicidialRecording(models.Model):
    _inherit = "codestra.vicidial.recording"
    _description = "VICIdial Recording Metadata Reference"
    _order = "started_at desc, id desc"

    recording_uid = fields.Char(required=True, index=True, readonly=True)
    contract_version = fields.Selection(
        [("1.0", "1.0")], required=True, default="1.0", readonly=True, index=True
    )
    vicidial_recording_id = fields.Char(index=True)
    vicidial_call_id = fields.Char(index=True)
    asterisk_uniqueid = fields.Char(index=True)
    lead_id = fields.Many2one("crm.lead", ondelete="set null", index=True)
    campaign_id = fields.Many2one(
        "codestra.vicidial.campaign", required=True, ondelete="restrict", index=True
    )
    campaign_key = fields.Char(
        related="campaign_id.campaign_id", store=True, readonly=True, index=True
    )
    agent_id = fields.Many2one(
        "codestra.vicidial.agent", required=True, ondelete="restrict", index=True
    )
    started_at = fields.Datetime(index=True)
    format = fields.Selection(FORMATS, required=True)
    codec = fields.Char()
    channels = fields.Integer()
    sample_rate_hz = fields.Integer()
    file_size_bytes = fields.Integer(required=True, default=0)
    sha256 = fields.Char(required=True, size=64)
    object_version_id = fields.Char(index=True, readonly=True)
    storage_status = fields.Selection(
        [
            ("reservation_pending", "Reservation pending"),
            ("upload_pending", "Upload pending"),
            ("verified", "Verified"),
            ("odoo_linked", "Odoo linked"),
            ("retention_pending", "Retention pending"),
            ("quarantined", "Quarantined"),
            ("failed", "Failed"),
        ],
        required=True,
        default="reservation_pending",
        index=True,
    )
    retention_class = fields.Selection(
        RETENTION_CLASSES, required=True, default="standard", index=True
    )
    retention_until = fields.Datetime(index=True)
    legal_hold = fields.Boolean(default=False, index=True)
    upload_attempts = fields.Integer(default=0, readonly=True)
    last_error = fields.Text(readonly=True)
    verified_at = fields.Datetime(readonly=True)
    verification_status = fields.Selection(
        [
            ("pending", "Pending"),
            ("verified", "Verified"),
            ("failed", "Failed"),
        ],
        required=True,
        default="pending",
        index=True,
    )
    odoo_link_status = fields.Selection(
        [("linked", "Linked"), ("quarantined", "Quarantined")],
        required=True,
        default="linked",
        index=True,
    )
    retention_status = fields.Selection(
        [("active", "Active"), ("pending", "Pending"), ("expired", "Expired")],
        required=True,
        default="active",
        index=True,
    )
    transcription_status = fields.Char(readonly=True)
    qa_status = fields.Char(readonly=True)
    updated_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    environment = fields.Selection(
        [("staging", "Staging"), ("test", "Test"), ("production", "Production")],
        required=True,
        index=True,
    )
    supervisor_notes = fields.Text()
    qa_classification = fields.Char()

    _recording_uid_unique = models.Constraint(
        "UNIQUE(recording_uid)", "Recording UID must be unique."
    )
    _duration_nonnegative = models.Constraint(
        "CHECK(duration_seconds >= 0)", "Duration cannot be negative."
    )
    _size_nonnegative = models.Constraint(
        "CHECK(file_size_bytes >= 0)", "File size cannot be negative."
    )
    _contract_version_v1 = models.Constraint(
        "CHECK(contract_version = '1.0')", "Contract version must equal 1.0."
    )
    _retention_until_required = models.Constraint(
        "CHECK(legal_hold OR retention_class = 'legal_hold' OR retention_until IS NOT NULL)",
        "Retention date is required unless legal hold applies.",
    )

    def _auto_init(self):
        result = super()._auto_init()
        self.env.cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
              codestra_vicidial_recording_object_version_unique
            ON codestra_vicidial_recording (object_version_id)
            WHERE object_version_id IS NOT NULL
            """
        )
        return result

    @api.constrains("sha256")
    def _check_sha256(self):
        for record in self:
            if not SHA256_RE.fullmatch(record.sha256 or ""):
                raise ValidationError(
                    "SHA-256 must be 64 lowercase hexadecimal characters."
                )

    @api.constrains("object_version_id")
    def _check_object_version_unique(self):
        for record in self.filtered("object_version_id"):
            duplicate = self.search_count(
                [
                    ("id", "!=", record.id),
                    ("object_version_id", "=", record.object_version_id),
                ]
            )
            if duplicate:
                raise ValidationError("Object version ID must be unique.")

    @api.constrains("call_id", "lead_id", "campaign_id", "agent_id")
    def _check_existing_links(self):
        for record in self:
            if not record.call_id or record.call_id.campaign_id != record.campaign_id:
                raise ValidationError("Recording must match an existing call campaign.")
            if record.call_id.agent_id != record.agent_id:
                raise ValidationError("Recording must match the existing call agent.")
            allowed_lead = record.call_id.crm_lead_id or record.call_id.lead_id
            if record.lead_id and record.lead_id != allowed_lead:
                raise ValidationError(
                    "Only the call's existing CRM lead may be linked."
                )

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            if values.get("contract_version", "1.0") != "1.0":
                raise ValidationError("Contract version must equal 1.0.")
            values["updated_at"] = fields.Datetime.now()
            self._set_retention_until(values)
        return super().create(values_list)

    def write(self, values):
        if "contract_version" in values and values["contract_version"] != "1.0":
            raise ValidationError("Contract version must equal 1.0.")
        if not self.env.is_superuser() and not self.env.user.has_group(
            "codestra_vicidial_recording.group_recording_administrator"
        ):
            if self.env.user.has_group(
                "codestra_vicidial_recording.group_recording_supervisor"
            ):
                allowed = {"supervisor_notes"}
            elif self.env.user.has_group(
                "codestra_vicidial_recording.group_recording_qa_reviewer"
            ):
                allowed = {"qa_classification"}
            else:
                raise AccessError("Recording metadata writes are denied.")
            if set(values) - allowed:
                raise AccessError("Recording metadata field write is not authorized.")
        retention_change = {"retention_class", "retention_until", "legal_hold"} & set(
            values
        )
        snapshots = {
            record.id: (
                record.retention_class,
                record.retention_until,
                record.legal_hold,
            )
            for record in self
        }
        values["updated_at"] = fields.Datetime.now()
        self._set_retention_until(values)
        result = super().write(values)
        if retention_change and not self.env.context.get("skip_retention_audit"):
            audit_model = self.env["codestra.vicidial.recording.retention.audit"].sudo()
            reason = self.env.context.get("retention_reason", "metadata update")
            for record in self:
                previous = snapshots[record.id]
                audit_model.create(
                    {
                        "recording_id": record.id,
                        "recording_uid": record.recording_uid,
                        "previous_retention_class": previous[0],
                        "new_retention_class": record.retention_class,
                        "previous_retention_until": previous[1],
                        "new_retention_until": record.retention_until,
                        "legal_hold_before": previous[2],
                        "legal_hold_after": record.legal_hold,
                        "actor_id": self.env.user.id,
                        "reason": reason,
                        "middleware_acknowledgement_status": "pending",
                    }
                )
        return result

    @staticmethod
    def _set_retention_until(values):
        retention_class = values.get("retention_class")
        if retention_class == "legal_hold" or values.get("legal_hold"):
            values["retention_until"] = False
        elif retention_class in RETENTION_DAYS and "retention_until" not in values:
            values["retention_until"] = fields.Datetime.now() + timedelta(
                days=RETENTION_DAYS[retention_class]
            )

    @api.ondelete(at_uninstall=False)
    def _no_direct_recording_delete(self):
        raise AccessError("Odoo cannot delete authoritative recording references.")

    def action_play_recording(self):
        self.ensure_one()
        user = self.env.user
        is_admin = user.has_group(
            "codestra_vicidial_recording.group_recording_administrator"
        )
        is_supervisor = user.has_group(
            "codestra_vicidial_recording.group_recording_supervisor"
        )
        is_qa = user.has_group(
            "codestra_vicidial_recording.group_recording_qa_reviewer"
        )
        group_ok = (
            self.agent_id.recording_scope_group_id in user.recording_scope_group_ids
        )
        campaign_ok = (
            is_admin
            or (is_supervisor and user in self.campaign_id.supervisor_ids)
            or (is_qa and self.campaign_id in user.recording_qa_campaign_ids)
        )
        authorized = is_admin or (campaign_ok and group_ok)
        role = (
            "administrator"
            if is_admin
            else "supervisor"
            if is_supervisor
            else "qa_reviewer"
            if is_qa
            else "denied"
        )
        audit_values = {
            "recording_id": self.id,
            "recording_uid": self.recording_uid,
            "user_id": user.id,
            "user_role": role,
            "campaign_scope_result": "allowed" if campaign_ok else "denied",
            "group_scope_result": "allowed" if group_ok or is_admin else "denied",
            "qa_scope_result": "allowed"
            if is_qa and campaign_ok and group_ok
            else "not_applicable"
            if not is_qa
            else "denied",
            "result": "granted" if authorized else "denied",
            "denial_reason": False
            if authorized
            else "campaign, group, or role scope denied",
            "client_ip_sanitized": self._sanitized_client_ip(),
        }
        if not authorized:
            self.env["codestra.vicidial.recording.playback.audit"].sudo().create(
                audit_values
            )
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "type": "danger",
                    "message": "Recording playback scope is unresolved or denied.",
                    "sticky": False,
                },
            }
        params = self.env["ir.config_parameter"].sudo()
        base_url = params.get_param("codestra.recording_middleware_url", "")
        token = params.get_param("codestra.recording_middleware_service_token", "")
        if not base_url.startswith("https://") or not token:
            raise UserError("Recording middleware service is unavailable.")
        response = requests.post(
            f"{base_url.rstrip('/')}/api/v1/recordings/{self.recording_uid}/playback-url",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Service-Identity": "codestra-odoo",
                "X-Codestra-Environment": self.environment,
            },
            json={
                "requester_type": "odoo",
                "user_level": 9 if is_admin else 8,
                "campaign_authorized": campaign_ok,
                "group_authorized": group_ok,
                "ttl_seconds": 120,
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        url = payload.get("playback_url")
        if not isinstance(url, str) or payload.get("expires_in", 121) > 120:
            raise UserError("Middleware returned an invalid playback grant.")
        audit_values["middleware_request_id"] = payload.get("request_id")
        self.env["codestra.vicidial.recording.playback.audit"].sudo().create(
            audit_values
        )
        return {
            "type": "ir.actions.client",
            "tag": "codestra_recording_playback",
            "params": {"url": url},
        }

    @staticmethod
    def _sanitized_client_ip():
        try:
            from odoo.http import request

            value = request.httprequest.remote_addr or ""
        except RuntimeError:
            value = ""
        if ":" in value:
            return value.split(":")[0] + "::/48"
        parts = value.split(".")
        return ".".join(parts[:3] + ["0/24"]) if len(parts) == 4 else False


class RetentionAudit(models.Model):
    _name = "codestra.vicidial.recording.retention.audit"
    _description = "Append-only recording retention audit"
    _order = "event_time desc, id desc"

    recording_id = fields.Many2one(
        "codestra.vicidial.recording", required=True, readonly=True, ondelete="restrict"
    )
    recording_uid = fields.Char(required=True, index=True, readonly=True)
    previous_retention_class = fields.Selection(RETENTION_CLASSES, readonly=True)
    new_retention_class = fields.Selection(
        RETENTION_CLASSES, required=True, readonly=True
    )
    previous_retention_until = fields.Datetime(readonly=True)
    new_retention_until = fields.Datetime(readonly=True)
    legal_hold_before = fields.Boolean(readonly=True)
    legal_hold_after = fields.Boolean(readonly=True)
    actor_id = fields.Many2one("res.users", required=True, readonly=True)
    event_time = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True
    )
    reason = fields.Text(required=True, readonly=True)
    middleware_acknowledgement_status = fields.Selection(
        [
            ("pending", "Pending"),
            ("acknowledged", "Acknowledged"),
            ("failed", "Failed"),
        ],
        required=True,
        default="pending",
        readonly=True,
    )
    middleware_acknowledgement_time = fields.Datetime(readonly=True)

    def write(self, values):
        if self.env.context.get("allow_middleware_acknowledgement") and set(values) <= {
            "middleware_acknowledgement_status",
            "middleware_acknowledgement_time",
        }:
            return super().write(values)
        raise AccessError("Retention audit is append-only.")

    @api.ondelete(at_uninstall=False)
    def _no_delete(self):
        raise AccessError("Retention audit is append-only.")


class PlaybackAudit(models.Model):
    _name = "codestra.vicidial.recording.playback.audit"
    _description = "Append-only recording playback audit"
    _order = "request_time desc, id desc"

    recording_id = fields.Many2one(
        "codestra.vicidial.recording", required=True, readonly=True, ondelete="restrict"
    )
    recording_uid = fields.Char(required=True, readonly=True, index=True)
    user_id = fields.Many2one("res.users", required=True, readonly=True)
    user_role = fields.Char(required=True, readonly=True)
    campaign_scope_result = fields.Char(required=True, readonly=True)
    group_scope_result = fields.Char(required=True, readonly=True)
    qa_scope_result = fields.Char(required=True, readonly=True)
    request_time = fields.Datetime(default=fields.Datetime.now, readonly=True)
    result = fields.Selection(
        [
            ("requested", "Requested"),
            ("granted", "Granted"),
            ("denied", "Denied"),
            ("failed", "Failed"),
        ],
        required=True,
        readonly=True,
    )
    denial_reason = fields.Char(readonly=True)
    client_ip_sanitized = fields.Char(readonly=True)
    middleware_request_id = fields.Char(readonly=True)

    def write(self, values):
        raise AccessError("Playback audit is append-only.")

    @api.ondelete(at_uninstall=False)
    def _no_delete(self):
        raise AccessError("Playback audit is append-only.")


class ApiIdempotency(models.Model):
    _name = "codestra.vicidial.recording.api.idempotency"
    _description = "Recording API idempotency audit"

    environment = fields.Char(required=True, readonly=True)
    idempotency_key = fields.Char(required=True, readonly=True)
    request_hash = fields.Char(required=True, readonly=True)
    recording_uid = fields.Char(required=True, readonly=True)
    acknowledgement_json = fields.Text(required=True, readonly=True)
    created_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    _environment_key_unique = models.Constraint(
        "UNIQUE(environment,idempotency_key)",
        "Recording API idempotency key must be unique per environment.",
    )

    def acknowledgement(self):
        self.ensure_one()
        return json.loads(self.acknowledgement_json)

    def write(self, values):
        raise AccessError("API audit is append-only.")

    @api.ondelete(at_uninstall=False)
    def _no_delete(self):
        raise AccessError("API audit is append-only.")


class ApiNonce(models.Model):
    _name = "codestra.vicidial.recording.api.nonce"
    _description = "Consumed recording API authentication nonce"

    environment = fields.Char(required=True, readonly=True)
    service_identity = fields.Char(required=True, readonly=True)
    nonce = fields.Char(required=True, readonly=True)
    request_timestamp = fields.Char(required=True, readonly=True)
    consumed_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    _environment_identity_nonce_unique = models.Constraint(
        "UNIQUE(environment,service_identity,nonce)",
        "Recording API nonce cannot be reused.",
    )

    def write(self, values):
        raise AccessError("Authentication nonce evidence is append-only.")

    @api.ondelete(at_uninstall=False)
    def _no_delete(self):
        raise AccessError("Authentication nonce evidence is append-only.")
