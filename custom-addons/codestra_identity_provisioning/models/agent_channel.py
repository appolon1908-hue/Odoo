from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

SERVICE_WRITE_FIELDS = {
    "external_system",
    "external_id",
    "external_reference",
    "state",
    "last_reconciled_at",
    "last_error_code",
    "last_error_sanitized",
}


class CodestraAgentChannel(models.Model):
    """Per-agent, per-channel provisioning *intent* and Odoo-side status.

    This model records what a Super Admin wants (``desired_enabled``,
    ``incoming_allowed``, ``outgoing_allowed``) and what Odoo has observed
    about the channel's provisioning lifecycle (``state``,
    ``external_id``/``external_reference``, ``last_reconciled_at``). It does
    not itself perform any external provisioning: no Keycloak, VICIdial,
    Asterisk, Middleware, email, or SMS call is made by this model or its
    migration. ``effective_access`` is intentionally only the Odoo-side half
    of the eventual safe-activation formula

        effective_X = agent_X_switch AND campaign_X_policy
                      AND global_PSTN_gate AND successful_readback

    -- the global-safety-gate and external-read-back terms require a live
    Middleware integration that does not exist yet and are out of scope for
    this model.
    """

    _name = "codestra.agent.channel"
    _description = "Per-Agent Channel Provisioning Intent"
    _inherit = ["mail.thread"]
    _order = "employee_id, channel_type"

    employee_id = fields.Many2one(
        "hr.employee", required=True, ondelete="cascade", index=True
    )
    odoo_user_id = fields.Many2one(
        "res.users", related="employee_id.user_id", store=True, readonly=True
    )
    membership_id = fields.Many2one(
        "cc.campaign.membership", ondelete="cascade", index=True
    )
    provisioning_request_id = fields.Many2one(
        "codestra.provisioning.request", ondelete="set null"
    )
    correlation_id = fields.Char(copy=False, index=True)

    campaign_id = fields.Many2one(
        related="membership_id.campaign_id", store=True, readonly=True
    )
    business_unit_id = fields.Many2one(
        related="membership_id.business_unit_id", store=True, readonly=True
    )
    supervisor_id = fields.Many2one(
        "res.users", compute="_compute_supervisor_id", store=True, readonly=True
    )

    channel_type = fields.Selection(
        [
            ("email", "Email"),
            ("sms", "SMS"),
            ("phone", "Phone"),
            ("webrtc", "WebRTC"),
        ],
        required=True,
        tracking=True,
    )

    desired_enabled = fields.Boolean(default=False, tracking=True)
    incoming_allowed = fields.Boolean(default=False, tracking=True)
    outgoing_allowed = fields.Boolean(default=False, tracking=True)
    state = fields.Selection(
        [
            ("requested", "Requested"),
            ("provisioning", "Provisioning"),
            ("provisioned", "Provisioned"),
            ("effective", "Effective"),
            ("revoked", "Revoked"),
            ("failed", "Failed"),
        ],
        default="requested",
        required=True,
        tracking=True,
    )
    effective_access = fields.Boolean(
        compute="_compute_effective_access", store=True, tracking=True
    )

    extension_assignment_id = fields.Many2one(
        "codestra.extension.assignment", ondelete="restrict"
    )
    extension = fields.Char(
        related="extension_assignment_id.extension", store=True, readonly=True
    )

    external_system = fields.Char(tracking=True)
    external_id = fields.Char(copy=False)
    external_reference = fields.Char(copy=False)
    last_reconciled_at = fields.Datetime(copy=False)
    last_error_code = fields.Char(copy=False)
    last_error_sanitized = fields.Char(copy=False)

    _employee_channel_unique = models.Constraint(
        "unique(employee_id, channel_type)",
        "An agent may have only one record per channel type.",
    )

    @api.depends("campaign_id.primary_supervisor_membership_id.user_id")
    def _compute_supervisor_id(self):
        for channel in self:
            supervisor_membership = channel.campaign_id.primary_supervisor_membership_id
            channel.supervisor_id = supervisor_membership.user_id

    @api.depends(
        "desired_enabled",
        "state",
        "employee_id.active",
        "campaign_id",
        "supervisor_id",
        "channel_type",
        "extension_assignment_id.state",
    )
    def _compute_effective_access(self):
        for channel in self:
            base = (
                channel.desired_enabled
                and channel.state == "effective"
                and channel.employee_id.active
                and bool(channel.campaign_id)
                and bool(channel.supervisor_id)
            )
            if channel.channel_type in ("phone", "webrtc"):
                base = base and bool(
                    channel.extension_assignment_id
                    and channel.extension_assignment_id.state == "committed"
                )
            channel.effective_access = base

    @api.constrains("extension_assignment_id")
    def _check_extension_not_6101(self):
        for channel in self:
            if (
                channel.extension_assignment_id
                and channel.extension_assignment_id.extension == "6101"
            ):
                raise ValidationError(
                    _("Extension 6101 is reserved from allocation.")
                )

    @api.constrains("extension_assignment_id", "employee_id")
    def _check_extension_belongs_to_employee(self):
        for channel in self:
            if (
                channel.extension_assignment_id
                and channel.extension_assignment_id.employee_id != channel.employee_id
            ):
                raise ValidationError(
                    _("This extension assignment belongs to a different employee.")
                )

    @api.constrains("channel_type", "incoming_allowed", "outgoing_allowed")
    def _check_no_voice_permissions_on_text_channels(self):
        for channel in self:
            if channel.channel_type in ("email", "sms") and (
                channel.incoming_allowed or channel.outgoing_allowed
            ):
                raise ValidationError(
                    _("Email and SMS channels cannot carry voice permissions.")
                )

    def write(self, values):
        user = self.env.user
        if user.has_group(
            "codestra_identity_provisioning.group_provisioning_service"
        ) and not user.has_group(
            "codestra_identity_provisioning.group_provisioning_global_super_admin"
        ):
            disallowed = set(values) - SERVICE_WRITE_FIELDS
            if disallowed:
                raise AccessError(
                    _(
                        "The provisioning integration service may only update "
                        "external status fields on this record."
                    )
                )
        return super().write(values)


class ProvisioningRequestAgentChannels(models.Model):
    _inherit = "codestra.provisioning.request"

    channel_ids = fields.One2many(
        "codestra.agent.channel", "provisioning_request_id", string="Agent Channels"
    )
