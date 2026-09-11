from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


SESSION_WRITE_CAPABILITY = object()


class CcCampaignMembershipTelephonyAssignment(models.Model):
    """Super-Admin-owned telephony assignment on a campaign membership.

    ``extension`` is reserved through the existing SIP extension pool
    (``codestra.extension.pool`` / ``codestra.extension.assignment`` in
    ``codestra_identity_provisioning``) and synced here by
    ``codestra.agent.onboarding._sync_reserved_identifiers_to_membership``.
    ``webrtc_enabled`` and ``sms_enabled`` are permission flags only: this
    module does not issue WebRTC credentials or send SMS itself, it carries
    the agent's intended permission state for a future Middleware consumer
    (see the ``telephony_assignment`` block of the
    ``agent.provisioning.requested.v1`` event payload).

    Write access to ``cc.campaign.membership`` is already restricted to
    ``codestra_cc_security.group_cc_global_administrator`` at the model-ACL
    level (``access_cc_membership_agent``/``access_cc_membership_specialist``
    are read-only) — no separate field-level guard is needed for these three
    fields; everyone else's visibility is already scoped by the existing
    ``rule_cc_membership_global_scope`` record rule.
    """

    _inherit = "cc.campaign.membership"

    extension = fields.Char(copy=False, index=True)
    webrtc_enabled = fields.Boolean(default=False, copy=False)
    sms_enabled = fields.Boolean(default=False, copy=False)
    webrtc_session_ids = fields.One2many(
        "cc.webrtc.session", "membership_id", string="WebRTC Sessions"
    )

    _extension_unique_active = models.UniqueIndex(
        "(extension) WHERE state = 'active' AND extension IS NOT NULL",
        "An extension may be assigned to only one active membership.",
    )

    def write(self, values):
        result = super().write(values)
        if "webrtc_enabled" in values and not values["webrtc_enabled"]:
            self.webrtc_session_ids.filtered(lambda s: not s.revoked_at)._revoke(
                _("WebRTC was disabled for this agent.")
            )
        return result


class CcWebrtcSession(models.Model):
    """Source-of-truth state and audit trail for an agent's single WebRTC
    device/browser session.

    This model does not itself issue, register, or terminate a real WebRTC
    credential with Asterisk — there is no session-issuer implementation to
    call yet (the legacy vendor webphone-session-issuer image is retained
    only as a rollback target; see
    ``docs/SERVER-RUNTIME-RECONCILIATION-MAP.md``). ``action_register`` is the
    integration point a future governed issuer should call once it exists;
    until then this simply enforces and records the max-1-device rule.
    """

    _name = "cc.webrtc.session"
    _description = "Agent WebRTC Device Session"
    _order = "issued_at desc, id desc"

    membership_id = fields.Many2one(
        "cc.campaign.membership", required=True, ondelete="restrict", index=True
    )
    device_label = fields.Char(copy=False)
    issued_at = fields.Datetime(required=True, default=fields.Datetime.now, copy=False)
    revoked_at = fields.Datetime(copy=False)
    revoked_reason = fields.Char(copy=False)
    active_session = fields.Boolean(
        compute="_compute_active_session", store=True, index=True
    )

    _one_active_session_per_membership = models.UniqueIndex(
        "(membership_id) WHERE revoked_at IS NULL",
        "An agent may have only one active WebRTC device session.",
    )

    @api.depends("revoked_at")
    def _compute_active_session(self):
        for session in self:
            session.active_session = not session.revoked_at

    @api.model_create_multi
    def create(self, values_list):
        if (
            self.env.context.get("_cc_webrtc_session_write")
            is not SESSION_WRITE_CAPABILITY
        ):
            raise AccessError(
                _("WebRTC sessions are created only through the governed issuer path.")
            )
        return super().create(values_list)

    def write(self, values):
        if (
            self.env.context.get("_cc_webrtc_session_write")
            is not SESSION_WRITE_CAPABILITY
        ):
            raise AccessError(_("WebRTC sessions cannot be edited directly."))
        return super().write(values)

    def unlink(self):
        raise AccessError(_("WebRTC session evidence is retained, not deleted."))

    @api.constrains("membership_id")
    def _check_webrtc_enabled(self):
        for session in self:
            if not session.membership_id.webrtc_enabled:
                raise ValidationError(
                    _("A WebRTC session requires WebRTC to be enabled on the membership.")
                )

    def _revoke(self, reason):
        if not self:
            return
        self.with_context(_cc_webrtc_session_write=SESSION_WRITE_CAPABILITY).write(
            {"revoked_at": fields.Datetime.now(), "revoked_reason": reason}
        )

    @api.model
    def action_register(self, membership, device_label):
        """Register a new device session, revoking any prior active one first.

        This is the integration point for a future governed WebRTC
        session-issuer; it only manages this model's state, it does not talk
        to Keycloak or Asterisk.
        """
        if not membership.webrtc_enabled:
            raise ValidationError(
                _("WebRTC is not enabled for this agent's membership.")
            )
        Session = self.with_context(_cc_webrtc_session_write=SESSION_WRITE_CAPABILITY)
        membership.webrtc_session_ids.filtered(lambda s: not s.revoked_at)._revoke(
            _("Replaced by a new device registration.")
        )
        return Session.create(
            {"membership_id": membership.id, "device_label": device_label}
        )
