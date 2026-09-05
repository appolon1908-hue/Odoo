import hashlib
import json

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .phone import normalize_phone

CALL_STATES = [
    ("new", "New"),
    ("initiating", "Initiating"),
    ("ringing", "Ringing"),
    ("offered", "Offered"),
    ("answering", "Answering"),
    ("connected", "Connected"),
    ("held", "Held"),
    ("transferring", "Transferring"),
    ("transferred", "Transferred"),
    ("ending", "Ending"),
    ("completed", "Completed"),
    ("failed", "Failed"),
    ("missed", "Missed"),
    ("rejected", "Rejected"),
    ("cancelled", "Cancelled"),
]
TERMINAL_STATES = {"completed", "failed", "missed", "rejected", "cancelled", "transferred"}
ALLOWED_TRANSITIONS = {
    None: {"new", "initiating", "ringing", "offered"},
    "new": {"initiating", "ringing", "offered", "cancelled", "failed"},
    "initiating": {
        "ringing", "connected", "completed", "missed", "rejected", "cancelled", "failed"
    },
    "ringing": {"offered", "answering", "connected", "missed", "rejected", "cancelled", "failed"},
    "offered": {"answering", "connected", "missed", "rejected", "cancelled", "failed"},
    "answering": {"connected", "rejected", "failed"},
    "connected": {"held", "transferring", "ending", "completed", "failed"},
    "held": {"connected", "transferring", "ending", "completed", "failed"},
    "transferring": {"connected", "transferred", "ending", "completed", "failed"},
    "ending": {"completed", "failed"},
}


class VicidialCallControl(models.Model):
    _inherit = "codestra.vicidial.call"

    call_id = fields.Char(index=True, copy=False)
    correlation_id = fields.Char(index=True, copy=False)
    last_event_id = fields.Char(index=True, copy=False)
    asterisk_uniqueid = fields.Char(index=True, copy=False)
    linkedid = fields.Char(index=True, copy=False)
    tenant_id = fields.Char(index=True)
    keycloak_subject = fields.Char(index=True, copy=False)
    business_unit_id = fields.Char(index=True)
    campaign_code = fields.Char(index=True)
    vicidial_user = fields.Char(index=True)
    extension = fields.Char(index=True)
    customer_id = fields.Many2one("res.partner", ondelete="set null", index=True)
    previous_state = fields.Selection(CALL_STATES, copy=False)
    state = fields.Selection(CALL_STATES, default="new", required=True, index=True, copy=False)
    ringing_at = fields.Datetime(copy=False)
    answered_at = fields.Datetime(copy=False)
    ended_at = fields.Datetime(copy=False)
    talk_duration = fields.Integer(default=0, copy=False)
    notes = fields.Text()
    recording_status = fields.Selection(
        [("disabled", "Disabled"), ("on", "On"), ("off", "Off"), ("paused", "Paused"), ("available", "Available")],
        default="disabled",
        required=True,
    )
    appointment_id = fields.Many2one("calendar.event", ondelete="set null")
    match_status = fields.Selection(
        [("exact", "Exact"), ("ambiguous", "Ambiguous"), ("none", "None")],
        default="none",
        required=True,
    )
    original_number = fields.Char()
    normalized_number = fields.Char(index=True)
    sequence = fields.Integer(default=0, required=True, copy=False)

    _call_public_id_unique = models.Constraint("UNIQUE(call_id)", "Call ID must be unique.")
    _asterisk_uniqueid_unique = models.Constraint(
        "UNIQUE(asterisk_uniqueid)", "Asterisk uniqueid must identify one call."
    )
    _call_durations_nonnegative = models.Constraint("CHECK(talk_duration >= 0)", "Talk duration cannot be negative.")

    @api.model
    def normalize_number(self, value):
        return normalize_phone(value)

    @api.model
    def match_customer(self, number, campaign_code=None):
        normalized = self.normalize_number(number)
        candidates = []
        Partner = self.env["res.partner"]
        Lead = self.env["crm.lead"]
        for partner in Partner.search([("x_codestra_phone_e164", "=", normalized)]):
            candidates.append(("partner", partner.id, partner.display_name, 2))
        for lead in Lead.search([("x_phone_e164", "=", normalized)]):
            priority = 0 if campaign_code and lead.vicidial_campaign_id == campaign_code else 1
            candidates.append(("lead", lead.id, lead.display_name, priority))
        candidates.sort(key=lambda item: (item[3] if len(item) > 3 else 2, item[0], item[1]))
        return {
            "normalized_number": normalized,
            "match": "none" if not candidates else "exact" if len(candidates) == 1 else "ambiguous",
            "matches": [{"model": row[0], "id": row[1], "name": row[2]} for row in candidates],
        }

    def _check_call_owner(self):
        self.ensure_one()
        user = self.env.user
        if user.has_group("codestra_vicidial_crm.group_manager"):
            return
        if (
            not self.agent_id
            or self.agent_id.odoo_user_id != user
            or not user.codestra_tenant_id
            or self.tenant_id != user.codestra_tenant_id
            or not user.keycloak_subject
            or self.keycloak_subject != user.keycloak_subject
        ):
            raise AccessError("The call is not assigned to the current agent.")

    def apply_authoritative_event(self, envelope):
        self.ensure_one()
        event_id = str(envelope.get("event_id") or "")
        incoming = str(envelope.get("state") or "").lower()
        sequence = int(envelope.get("sequence") or 0)
        event_type = str(envelope.get("event_type") or "")
        metadata_event = event_type in {"call.recording_available", "call.disposition_required"}
        if not event_id or (not metadata_event and incoming not in dict(CALL_STATES)):
            raise ValidationError("Canonical event ID and a supported state are required.")
        raw = json.dumps(
            envelope,
            sort_keys=True,
            separators=(",", ":"),
            default=lambda value: fields.Datetime.to_string(value),
        )
        digest = hashlib.sha256(raw.encode()).hexdigest()
        prior = self.env["codestra.vicidial.call.event"].search([("idempotency_key", "=", event_id)], limit=1)
        if prior:
            if prior.call_id != self or prior.payload_hash != digest:
                raise ValidationError("Event ID conflicts with different lifecycle evidence.")
            return {"duplicate": True, "state": self.state, "call_id": self.call_id}
        current = self.state or None
        applied = sequence > self.sequence and (metadata_event or incoming in ALLOWED_TRANSITIONS.get(current, set()))
        if current in TERMINAL_STATES and not metadata_event:
            applied = False
        values = {"last_event_id": event_id}
        if applied:
            values["sequence"] = sequence
            if not metadata_event:
                values.update({"previous_state": current, "state": incoming})
            timestamp = envelope.get("timestamp")
            if incoming in {"ringing", "offered"} and not self.ringing_at:
                values["ringing_at"] = timestamp
            if incoming == "connected" and not self.answered_at:
                values["answered_at"] = timestamp
                values["connected_at"] = timestamp
            if incoming in TERMINAL_STATES and not self.ended_at:
                values["ended_at"] = timestamp
                values["end_at"] = timestamp
                values["wrap_up_started_at"] = timestamp
                values["talk_duration"] = max(0, int(envelope.get("talk_duration") or 0))
                values["duration_seconds"] = max(0, int(envelope.get("duration") or 0))
            if event_type == "call.recording_available":
                recording_id = str(envelope.get("recording_id") or "")
                if not recording_id:
                    raise ValidationError("Recording metadata requires a recording ID.")
                self.env["codestra.vicidial.recording"].sudo().create(
                    {
                        "call_id": self.id,
                        "recording_id": recording_id,
                        "filename": envelope.get("recording_reference"),
                        "duration_seconds": max(0, int(envelope.get("duration") or 0)),
                        "available": True,
                        "access_level": "restricted",
                        "created_at": timestamp,
                    }
                )
                values["recording_status"] = "available"
            if event_type == "call.transfer.completed":
                self.env["codestra.vicidial.transfer"].sudo().create(
                    {
                        "call_id": self.id,
                        "from_agent_id": self.agent_id.id,
                        "to_queue": envelope.get("transfer_destination"),
                        "transfer_type": envelope.get("transfer_type") or "blind",
                        "requested_at": timestamp,
                        "completed_at": timestamp,
                        "status": "completed",
                        "external_transfer_id": event_id,
                    }
                )
        self.write(values)
        self.env["codestra.vicidial.call.event"].sudo().create(
            {
                "event_type": envelope.get("event_type") or "call." + incoming,
                "occurred_at": envelope.get("timestamp"),
                "call_id": self.id,
                "agent_id": self.agent_id.id,
                "campaign_id": self.campaign_id.id,
                "payload_json": raw,
                "payload_hash": digest,
                "idempotency_key": event_id,
                "processing_state": "processed",
                "processed_at": fields.Datetime.now(),
                "correlation_id": self.correlation_id,
                "source": envelope.get("source") or "middleware",
                "sequence": sequence,
            }
        )
        if applied:
            self._notify_agent()
        return {"duplicate": False, "applied": applied, "state": self.state, "call_id": self.call_id}

    def _notify_agent(self):
        self.ensure_one()
        if not self.agent_id.odoo_user_id:
            return
        payload = self.with_user(self.agent_id.odoo_user_id).agent_payload()
        self.env["bus.bus"]._sendone(self.agent_id.odoo_user_id.partner_id, "codestra.call", payload)

    def agent_payload(self):
        self.ensure_one()
        self._check_call_owner()
        lead = self.crm_lead_id or self.lead_id
        return {
            "call_id": self.call_id,
            "correlation_id": self.correlation_id,
            "state": self.state,
            "previous_state": self.previous_state,
            "sequence": self.sequence,
            "direction": self.direction,
            "caller_number": self.normalized_number or self.caller_id,
            "customer": {"id": self.customer_id.id, "name": self.customer_id.display_name}
            if self.customer_id
            else None,
            "lead": {"id": lead.id, "name": lead.display_name} if lead else None,
            "campaign": self.campaign_code or self.campaign_id.campaign_id,
            "business_unit": self.business_unit_id,
            "extension": self.extension,
            "ringing_at": self.ringing_at,
            "answered_at": self.answered_at,
            "ended_at": self.ended_at,
            "recording_status": self.recording_status,
            "notes": self.notes or "",
            "match_status": self.match_status,
            "agent_status": self._workspace_agent_status(),
            "wrap_up_timeout_seconds": self.campaign_id.wrap_up_timeout_seconds,
            "call_control_enabled": self.env["codestra.feature.flags"].flag_enabled("call_control_enabled"),
            "transfer_control_enabled": self.env["codestra.feature.flags"].flag_enabled("transfer_control_enabled"),
            "appointment": {
                "id": self.appointment_id.id,
                "name": self.appointment_id.display_name,
                "start": self.appointment_id.start,
            }
            if self.appointment_id
            else None,
        }

    def _workspace_agent_status(self):
        self.ensure_one()
        if self.state in {"offered", "ringing", "answering"}:
            return "ringing"
        if self.state in {"connected", "transferring"}:
            return "on_call"
        if self.state == "held":
            return "hold"
        if self.state in TERMINAL_STATES and not self.wrap_up_completed_at:
            return "wrap_up"
        return {"active": "ready", "paused": "break"}.get(self.agent_id.status, self.agent_id.status or "offline")


class CallControlCommand(models.Model):
    _name = "codestra.call.control.command"
    _description = "Idempotent Call Control Command"
    _order = "create_date desc"

    idempotency_key = fields.Char(required=True, index=True, readonly=True)
    request_hash = fields.Char(required=True, readonly=True)
    call_id = fields.Many2one("codestra.vicidial.call", required=True, ondelete="restrict", readonly=True)
    action = fields.Selection(
        [
            (value, value.title())
            for value in (
                "outbound",
                "answer",
                "decline",
                "hangup",
                "hold",
                "resume",
                "transfer",
                "notes",
                "disposition",
                "callback",
            )
        ],
        required=True,
        readonly=True,
    )
    actor_id = fields.Many2one("res.users", required=True, readonly=True)
    correlation_id = fields.Char(required=True, index=True, readonly=True)
    payload_json = fields.Text(required=True, readonly=True)
    state = fields.Selection(
        [("queued", "Queued"), ("confirmed", "Confirmed"), ("failed", "Failed")],
        default="queued",
        required=True,
        readonly=True,
    )
    result_json = fields.Text(readonly=True)

    _command_idempotency_unique = models.Constraint(
        "UNIQUE(idempotency_key)", "Call-control idempotency key already exists."
    )

    def write(self, values):
        allowed = {"state", "result_json"}
        if set(values) - allowed or not self.env.user.has_group("codestra_vicidial_crm.group_integration_admin"):
            raise AccessError("Call-control command evidence is immutable.")
        return super().write(values)

    def _record_callback_result(self, callback):
        """Bind one confirmed callback command to its immutable result."""
        self.ensure_one()
        callback.ensure_one()
        if (
            self.action != "callback"
            or self.state != "confirmed"
            or callback._name != "codestra.callback"
            or callback.call_id != self.call_id
        ):
            raise ValidationError("Callback result does not match this command.")
        result = json.dumps({"callback_id": callback.id}, sort_keys=True)
        if self.result_json and self.result_json != result:
            raise ValidationError("Call-control command result is already bound.")
        if not self.result_json:
            super(CallControlCommand, self.sudo()).write({"result_json": result})
        return True

    def unlink(self):
        raise AccessError("Call-control command evidence is immutable.")
