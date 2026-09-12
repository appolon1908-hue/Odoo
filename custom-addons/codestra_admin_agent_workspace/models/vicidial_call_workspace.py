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
        help="crm.lead sharing this call's customer_id, most recently "
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

    @api.depends("state", "answered_at", "ended_at", "customer_id")
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
            lead = (
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

    def action_apply_workspace_disposition(self, disposition_id=None, notes=None):
        """Record disposition_id/notes for the agent's own call.

        codestra.vicidial.call's own ACL grants group_agent read-only
        access (access_call_user, custom-addons/codestra_vicidial_crm/
        security/ir.model.access.csv) - deliberately not widened here, so
        this is only reachable through the wizard in
        workspace_disposition_wizard.py, whose own (new, ungoverned) ACL
        is what actually lets an agent trigger it. _check_call_owner()
        (defined on the base model this class extends) is the real
        authorization check; sudo() only reaches the write this
        already-authorized caller needs, the same pattern
        codestra.platform.user.action_ensure_odoo_access() uses.
        """
        self.ensure_one()
        self._check_call_owner()
        values = {}
        if disposition_id is not None:
            values["disposition_id"] = disposition_id
        if notes is not None:
            values["notes"] = notes
        if values:
            self.sudo().write(values)
        return True
