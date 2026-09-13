import hashlib
import json

from odoo.exceptions import AccessError, ValidationError
from odoo import _, api, fields, models

# codestra.vicidial.call has no method for agent-initiated mute/hold/
# transfer/end - those are real-time SIP/Asterisk actions that happen on the
# softphone/WebRTC client, never through an Odoo write. This model is a
# server-of-record projection updated only via apply_authoritative_event()
# (see call_control.py). The Agent Workspace's Phone panel therefore shows
# live state read-only and offers the one action this record actually owns:
# recording the wrap-up disposition/notes once the call is done.
ACTIVE_CALL_STATES = (
    "new", "initiating", "ringing", "offered", "answering", "connected", "held",
    "transferring",
)


class CodestraVicidialCallWorkspace(models.Model):
    _inherit = "codestra.vicidial.call"

    workspace_duration_display = fields.Char(
        compute="_compute_workspace_fields",
        string="Duration",
    )
    workspace_is_active = fields.Boolean(
        compute="_compute_workspace_fields",
        string="Active Call",
    )
    workspace_lead_id = fields.Many2one(
        "crm.lead",
        compute="_compute_workspace_fields",
        string="Matched Lead",
        help="The explicitly linked lead, falling back to the customer's most recently "
        "written first. Read-only projection for display; opening the full "
        "lead record (action_open_workspace_lead) is the supported way to "
        "edit lead fields, activities, or chatter.",
    )
    workspace_recent_activity = fields.Html(
        compute="_compute_workspace_fields",
        string="Recent Activity",
        sanitize=True,
        help="Read-only summary of the matched lead's last 5 chatter "
        "messages. codestra.vicidial.call itself has no mail.thread mixin "
        "(no chatter of its own) - this reads crm.lead's real messages "
        "rather than embedding a widget that would not bind to this "
        "record. Open the lead (action_open_workspace_lead) for the full "
        "chatter/activities.",
    )

    @api.depends("state", "answered_at", "ended_at", "customer_id", "crm_lead_id", "lead_id")
    def _compute_workspace_fields(self):
        now = fields.Datetime.now()
        for call in self:
            call.workspace_is_active = call.state in ACTIVE_CALL_STATES
            start = call.answered_at
            end = call.ended_at or (now if call.workspace_is_active else None)
            if start and end:
                seconds = max(0, int((end - start).total_seconds()))
                call.workspace_duration_display = "%02d:%02d" % divmod(seconds, 60)
            else:
                call.workspace_duration_display = "00:00"
            lead = call.crm_lead_id or call.lead_id or (
                self.env["crm.lead"].search(
                    [("partner_id", "=", call.customer_id.id)],
                    order="write_date desc", limit=1,
                )
                if call.customer_id
                else self.env["crm.lead"]
            )
            call.workspace_lead_id = lead
            call.workspace_recent_activity = call._workspace_activity_html(lead)

    @api.model
    def _workspace_activity_html(self, lead):
        if not lead:
            return "<p><em>No matched lead.</em></p>"
        messages = self.env["mail.message"].search(
            [("model", "=", "crm.lead"), ("res_id", "=", lead.id),
             ("message_type", "=", "comment")],
            order="date desc", limit=5,
        )
        if not messages:
            return "<p><em>No recent activity.</em></p>"
        rows = "".join(
            "<li><strong>%s</strong> — %s</li>"
            % (message.date, message.body or "")
            for message in messages
        )
        return "<ul>%s</ul>" % rows

    def action_open_workspace_lead(self):
        self.ensure_one()
        if not self.workspace_lead_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("Lead"),
            "res_model": "crm.lead",
            "view_mode": "form",
            "res_id": self.workspace_lead_id.id,
        }

    def action_apply_workspace_disposition(self, disposition_id=None, notes=None, idempotency_key=None):
        """Apply the governed terminal-call workflow with durable replay evidence."""
        self.ensure_one()
        self.check_access("read")
        self._check_call_owner()
        if not isinstance(idempotency_key, str) or not 16 <= len(idempotency_key) <= 255:
            raise ValidationError("A valid Idempotency-Key is required.")
        # Serialize retries and competing outcomes for this call. Odoo retries
        # serialization failures with a fresh transaction snapshot.
        self.lock_for_update()
        self.invalidate_recordset()
        if self.state not in {"completed", "failed", "missed", "rejected", "cancelled", "transferred"}:
            raise ValidationError("Disposition is available only after a terminal call event.")
        disposition = self.env["codestra.vicidial.disposition"].browse(disposition_id).exists()
        if not disposition or not disposition.active or (
                self.campaign_id.allowed_disposition_ids
                and disposition not in self.campaign_id.allowed_disposition_ids):
            raise AccessError("Disposition is not valid for this campaign.")
        if disposition.requires_note and not (notes or "").strip():
            raise ValidationError("This disposition requires notes.")
        raw = json.dumps({"disposition_id": disposition.id, "notes": notes or ""}, sort_keys=True)
        digest = hashlib.sha256((str(self.id) + "\ndisposition\n" + raw).encode()).hexdigest()
        Command = self.env["codestra.call.control.command"].sudo()
        prior = Command.search([("idempotency_key", "=", idempotency_key)], limit=1)
        if prior:
            if prior.request_hash != digest or prior.call_id != self or prior.actor_id != self.env.user:
                raise ValidationError("Idempotency-Key conflicts with a different command.")
            return True
        completed_at = fields.Datetime.now()
        seconds = max(0, int((completed_at - self.wrap_up_started_at).total_seconds())) if self.wrap_up_started_at else 0
        command = Command.create({
            "idempotency_key": idempotency_key, "request_hash": digest,
            "call_id": self.id, "action": "disposition", "actor_id": self.env.user.id,
            "correlation_id": self.correlation_id, "payload_json": raw, "state": "confirmed",
        })
        self.sudo().write({"disposition_id": disposition.id, "notes": notes or self.notes,
                           "sub_disposition_id": False, "wrap_up_completed_at": completed_at,
                           "wrap_up_seconds": seconds})
        self.env["codestra.integration.audit"].sudo().create({
            "actor_user_id": self.env.user.id, "action": "call.disposition", "model_name": self._name,
            "record_res_id": self.id, "correlation_id": self.correlation_id,
            "after_json": json.dumps({"command_id": command.id, "disposition": disposition.code}),
            "success": True,
        })
        return True
