from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


CHANNEL_TRANSITION_CAPABILITY = object()
GLOBAL_ADMIN_GROUP = "codestra_cc_security.group_cc_global_administrator"

CHANNEL_TYPES = (
    ("email", "Email"),
    ("sms", "SMS"),
    ("phone", "Phone"),
    ("webrtc", "WebRTC"),
)
VOICE_CHANNELS = {"phone", "webrtc"}
CHANNEL_STATES = (
    ("requested", "Requested"),
    ("provisioned", "Provisioned"),
    ("effective", "Effective"),
    ("disabled", "Disabled"),
    ("failed", "Failed"),
)


class AgentChannel(models.Model):
    """The desired/effective channel projection for one campaign membership.

    This is an Odoo data model only. It does not send mail/SMS, issue WebRTC
    credentials, or dial the PSTN. Those actions remain behind the governed
    provisioning and Middleware contracts.
    """

    _name = "codestra.agent.channel"
    _description = "Agent Provisioning Channel"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "employee_id, channel_type, id"

    employee_id = fields.Many2one(
        "hr.employee",
        required=True,
        ondelete="restrict",
        index=True,
        copy=False,
    )
    user_id = fields.Many2one(
        "res.users",
        related="employee_id.user_id",
        store=True,
        readonly=True,
        index=True,
    )
    membership_id = fields.Many2one(
        "cc.campaign.membership",
        required=True,
        ondelete="restrict",
        index=True,
        copy=False,
    )
    onboarding_id = fields.Many2one(
        "codestra.agent.onboarding",
        ondelete="restrict",
        index=True,
        copy=False,
        readonly=True,
    )
    provisioning_request_id = fields.Many2one(
        "codestra.provisioning.request",
        ondelete="restrict",
        index=True,
        copy=False,
        readonly=True,
    )
    supervisor_id = fields.Many2one(
        "res.users",
        required=True,
        ondelete="restrict",
        index=True,
        copy=False,
    )
    channel_type = fields.Selection(
        CHANNEL_TYPES,
        required=True,
        index=True,
        copy=False,
    )
    desired_enabled = fields.Boolean(default=False, copy=False, tracking=True)
    state = fields.Selection(
        CHANNEL_STATES,
        required=True,
        default="requested",
        index=True,
        copy=False,
        tracking=True,
    )
    effective_access = fields.Boolean(
        compute="_compute_effective_access",
        store=True,
        readonly=True,
        index=True,
    )
    incoming_allowed = fields.Boolean(default=False, copy=False)
    outgoing_allowed = fields.Boolean(default=False, copy=False)
    extension = fields.Char(
        related="membership_id.extension",
        store=True,
        readonly=True,
        index=True,
    )
    endpoint_reference = fields.Char(copy=False, readonly=True)
    external_id = fields.Char(copy=False, readonly=True)
    external_reference = fields.Char(copy=False, readonly=True)
    readback_evidence_hash = fields.Char(copy=False, readonly=True)

    _membership_channel_unique = models.Constraint(
        "unique(membership_id, channel_type)",
        "Each campaign membership may have one record per channel.",
    )
    _agent_webrtc_unique = models.UniqueIndex(
        "(employee_id) WHERE channel_type = 'webrtc'",
        "An agent may have only one WebRTC endpoint.",
    )

    @api.model
    def _require_global_administrator(self):
        if not self.env.su and not self.env.user.has_group(GLOBAL_ADMIN_GROUP):
            raise AccessError(
                _("Only a global contact-center administrator may manage agent channels.")
            )

    @api.model_create_multi
    def create(self, values_list):
        self._require_global_administrator()
        for values in values_list:
            if values.get("state", "requested") != "requested":
                raise ValidationError(
                    _("New channel records must start in Requested state.")
                )
        return super().create(values_list)

    def write(self, values):
        self._require_global_administrator()
        if "state" in values and (
            self.env.context.get("_codestra_agent_channel_transition")
            is not CHANNEL_TRANSITION_CAPABILITY
        ):
            raise AccessError(
                _("Channel state changes require verified provisioning read-back.")
            )
        if {"employee_id", "membership_id", "campaign_id", "channel_type"}.intersection(
            values
        ):
            for channel in self:
                if channel.state not in {"requested", "failed", "disabled"}:
                    raise AccessError(
                        _("Provisioned channel identity is immutable.")
                    )
        return super().write(values)

    def unlink(self):
        self._require_global_administrator()
        if any(channel.state in {"provisioned", "effective"} for channel in self):
            raise AccessError(_("Provisioned channel evidence cannot be deleted."))
        return super().unlink()

    @api.depends(
        "desired_enabled",
        "state",
        "employee_id.active",
        "user_id.active",
        "membership_id.state",
        "membership_id.last_sync_status",
        "membership_id.read_back_evidence",
        "membership_id.extension",
        "campaign_id.active",
        "campaign_id.lifecycle_state",
        "extension",
        "incoming_allowed",
        "outgoing_allowed",
    )
    def _compute_effective_access(self):
        for channel in self:
            membership = channel.membership_id
            enabled = bool(
                channel.desired_enabled
                and channel.state == "effective"
                and channel.employee_id.active
                and channel.user_id.active
                and channel.campaign_id.active
                and channel.campaign_id.lifecycle_state
                in {"staging_ready", "activation_pending", "active"}
                and membership.state == "active"
                and membership.last_sync_status == "matched"
                and membership.read_back_evidence
            )
            if channel.channel_type in VOICE_CHANNELS:
                enabled = bool(
                    enabled
                    and channel.extension
                    and (channel.incoming_allowed or channel.outgoing_allowed)
                )
            channel.effective_access = enabled

    @api.constrains(
        "employee_id",
        "user_id",
        "membership_id",
        "campaign_id",
        "supervisor_id",
        "channel_type",
        "desired_enabled",
        "state",
        "incoming_allowed",
        "outgoing_allowed",
        "extension",
    )
    def _check_channel_binding(self):
        for channel in self:
            membership = channel.membership_id
            if not membership or membership.employee_id != channel.employee_id:
                raise ValidationError(
                    _("The channel employee must match the campaign membership.")
                )
            if membership.user_id != channel.user_id:
                raise ValidationError(
                    _("The channel user must match the campaign membership.")
                )
            if membership.campaign_id != channel.campaign_id:
                raise ValidationError(
                    _("The channel campaign must match the campaign membership.")
                )
            if channel.onboarding_id and (
                channel.onboarding_id.employee_id != channel.employee_id
                or channel.onboarding_id.campaign_id != channel.campaign_id
            ):
                raise ValidationError(
                    _("The channel onboarding link does not match the assignment.")
                )
            if channel.provisioning_request_id and (
                channel.provisioning_request_id.employee_id != channel.employee_id
                or channel.provisioning_request_id.cc_membership_id != membership
            ):
                raise ValidationError(
                    _("The channel provisioning request does not match the assignment.")
                )

            legacy_campaign = channel.campaign_id.legacy_campaign_id
            if channel.supervisor_id not in legacy_campaign.supervisor_ids:
                primary = channel.campaign_id.primary_supervisor_membership_id
                if not primary or primary.user_id != channel.supervisor_id:
                    raise ValidationError(
                        _("The supervisor must be approved for the campaign.")
                    )

            if channel.channel_type in {"email", "sms"} and (
                channel.incoming_allowed or channel.outgoing_allowed
            ):
                raise ValidationError(
                    _("Incoming/outgoing permissions apply only to voice channels.")
                )
            if channel.state in {"provisioned", "effective"} and channel.channel_type in VOICE_CHANNELS:
                if not channel.extension:
                    raise ValidationError(
                        _("A provisioned voice channel requires a reserved extension.")
                    )
            # State records the last external lifecycle evidence while the
            # desired_enabled field is the local switch. A Super Admin may turn
            # desired access off immediately; effective_access then closes
            # locally while the governed disable operation catches up.

    @api.model
    def ensure_for_onboarding(self, onboarding, membership, request):
        self._require_global_administrator()
        onboarding.ensure_one()
        membership.ensure_one()
        request.ensure_one()
        if (
            onboarding.employee_id != membership.employee_id
            or onboarding.campaign_id != membership.campaign_id
            or request.cc_membership_id != membership
        ):
            raise ValidationError(_("Channel setup is bound to the approved assignment."))

        voice_incoming = bool(onboarding.incoming_calls_enabled)
        voice_outgoing = bool(onboarding.outgoing_calls_enabled)
        if not onboarding.needs_sip_endpoint:
            voice_incoming = voice_outgoing = False

        desired = {
            "email": bool(onboarding.needs_company_email),
            "sms": bool(onboarding.sms_enabled),
            "phone": bool(onboarding.needs_sip_endpoint),
            "webrtc": bool(onboarding.webrtc_enabled),
        }
        channels = self.browse()
        for channel_type, is_enabled in desired.items():
            values = {
                "employee_id": onboarding.employee_id.id,
                "campaign_id": onboarding.campaign_id.id,
                "membership_id": membership.id,
                "onboarding_id": onboarding.id,
                "provisioning_request_id": request.id,
                "supervisor_id": onboarding.supervisor_id.id,
                "channel_type": channel_type,
                "desired_enabled": is_enabled,
                "incoming_allowed": (
                    voice_incoming if channel_type in VOICE_CHANNELS else False
                ),
                "outgoing_allowed": (
                    voice_outgoing if channel_type in VOICE_CHANNELS else False
                ),
            }
            existing = self.search(
                [
                    ("membership_id", "=", membership.id),
                    ("channel_type", "=", channel_type),
                ],
                limit=1,
            )
            if existing:
                if existing.state not in {"requested", "failed", "disabled"}:
                    immutable = {
                        "desired_enabled": is_enabled,
                        "incoming_allowed": values["incoming_allowed"],
                        "outgoing_allowed": values["outgoing_allowed"],
                    }
                    if any(existing[field] != value for field, value in immutable.items()):
                        raise ValidationError(
                            _("Provisioned channel permissions are immutable.")
                        )
                else:
                    existing.write({
                        "desired_enabled": is_enabled,
                        "incoming_allowed": values["incoming_allowed"],
                        "outgoing_allowed": values["outgoing_allowed"],
                    })
                channels |= existing
            else:
                channels |= self.create(values)
        return channels

    def _apply_provisioning_step(
        self,
        request,
        target_system,
        step_state,
        evidence_hash=False,
        external_id=False,
        external_reference=False,
    ):
        """Project verified service evidence onto the local channel record."""
        target_to_type = {
            "email": "email",
            "email_provider": "email",
            "sip": "phone",
            "webrtc": "webrtc",
            "sms": "sms",
        }
        channel_type = target_to_type.get(target_system)
        if not channel_type:
            return True
        channels = self.search([
            ("provisioning_request_id", "=", request.id),
            ("channel_type", "=", channel_type),
        ])
        if not channels:
            return True
        for channel in channels:
            if step_state in {"succeeded", "verified"}:
                state = "provisioned" if channel.desired_enabled else "disabled"
            elif step_state in {"failed", "blocked"}:
                state = "failed"
            else:
                state = "requested"
            values = {
                "state": state,
                "readback_evidence_hash": evidence_hash or False,
                "external_id": external_id or False,
                "external_reference": external_reference or False,
            }
            channel.with_context(
                _codestra_agent_channel_transition=CHANNEL_TRANSITION_CAPABILITY
            ).write(values)
        return True

    def mark_effective_for_membership(self, membership):
        self._require_global_administrator()
        channels = self.search([("membership_id", "=", membership.id)])
        if membership.state != "active" or membership.last_sync_status != "matched":
            raise ValidationError(
                _("Effective channels require an active, read-back-matched membership.")
            )
        for channel in channels:
            state = "effective" if channel.desired_enabled else "disabled"
            channel.with_context(
                _codestra_agent_channel_transition=CHANNEL_TRANSITION_CAPABILITY
            ).write({"state": state})
        return channels
