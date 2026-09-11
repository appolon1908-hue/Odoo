import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

SERVICE_WRITE_FIELDS = {
    "external_system",
    "external_id",
    "provider_reference",
    "state",
    "last_verified_at",
    "last_error_code",
    "last_error_message",
    "provider",
    "last_provisioning_job_id",
}
TRANSITION_CAPABILITY = object()
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
SAFE_CAMPAIGN_LIFECYCLE_STATES = {"staging_ready", "activation_pending", "active"}


class CodestraAgentChannel(models.Model):
    """Per-agent, per-channel provisioning *intent* and Odoo-side status.

    This model records what a Super Admin wants (``desired_enabled``,
    ``incoming_allowed``, ``outgoing_allowed``) and what Odoo has observed
    about the channel's provisioning lifecycle (``state``,
    ``external_id``/``provider_reference``, ``last_verified_at``). It does
    not itself perform any external provisioning: no Keycloak, VICIdial,
    Asterisk, Middleware, email, or SMS call is made by this model or its
    migration.

    ``state`` may only be changed through a governed transition (see
    ``TRANSITION_CAPABILITY``): ``_apply_step_evidence`` (real read-back
    evidence from ``codestra.provisioning.request.apply_service_callback``,
    for the ``email``/``phone`` channels that actually have a corresponding
    provisioning step today) and ``_mark_effective`` (called from
    ``codestra.agent.onboarding.action_activate`` once the campaign
    membership itself is fully active and synced). A bare write to
    ``state`` - even by a Super Admin - is rejected outside those paths.

    ``effective_access`` folds in real membership synchronization state
    (``last_sync_status``/``read_back_evidence``) and campaign lifecycle,
    not just this record's own fields - this is still the Odoo-side half of
    the eventual safe-activation formula

        effective_X = agent_X_switch AND campaign_X_policy
                      AND global_PSTN_gate AND successful_readback

    -- the global-PSTN-safety-gate term requires a live Middleware
    integration that does not exist yet and stays out of scope for this
    model; ``sms``/``webrtc`` channels have no external provisioning step at
    all today (this module never issues WebRTC credentials or sends SMS
    itself), so for those two ``successful_readback`` can only ever be
    satisfied by the governed ``_mark_effective`` activation path, not by
    real external evidence.
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
    # Standardized read-only projections of desired_enabled/state, so callers
    # (and the sibling codestra.platform.user / codestra.agent.account model
    # family) can query intent-vs-outcome without re-deriving the mapping.
    # desired_enabled/state remain the single source of truth; these are
    # deliberately not separate writable columns.
    requested_state = fields.Selection(
        [("not_requested", "Not Requested"), ("requested", "Requested")],
        compute="_compute_requested_state", store=True,
    )
    provisioned_state = fields.Selection(
        [("not_provisioned", "Not Provisioned"), ("provisioned", "Provisioned")],
        compute="_compute_provisioned_state", store=True,
    )

    extension_assignment_id = fields.Many2one(
        "codestra.extension.assignment", ondelete="restrict"
    )
    extension = fields.Char(
        related="extension_assignment_id.extension", store=True, readonly=True
    )

    provider = fields.Char(
        tracking=True,
        help="The third-party provider actually handling this channel "
        "(e.g. klyrow, telnexa, vicidial) - distinct from external_system, "
        "which is the internal step-target vocabulary.",
    )
    last_provisioning_job_id = fields.Char(copy=False)
    external_system = fields.Char(tracking=True)
    external_id = fields.Char(copy=False)
    provider_reference = fields.Char(copy=False)
    last_verified_at = fields.Datetime(copy=False)
    last_error_code = fields.Char(copy=False)
    last_error_message = fields.Char(copy=False)

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
        "membership_id.state",
        "membership_id.last_sync_status",
        "membership_id.read_back_evidence",
        "campaign_id.lifecycle_state",
    )
    def _compute_effective_access(self):
        for channel in self:
            membership = channel.membership_id
            base = (
                channel.desired_enabled
                and channel.state == "effective"
                and channel.employee_id.active
                and bool(channel.campaign_id)
                and bool(channel.supervisor_id)
                and membership
                and membership.state == "active"
                and membership.last_sync_status == "matched"
                and bool(membership.read_back_evidence)
                and channel.campaign_id.lifecycle_state
                in SAFE_CAMPAIGN_LIFECYCLE_STATES
            )
            if channel.channel_type in ("phone", "webrtc"):
                base = base and bool(
                    channel.extension_assignment_id
                    and channel.extension_assignment_id.state == "committed"
                )
            channel.effective_access = base

    @api.depends("desired_enabled")
    def _compute_requested_state(self):
        for channel in self:
            channel.requested_state = (
                "requested" if channel.desired_enabled else "not_requested"
            )

    @api.depends("state")
    def _compute_provisioned_state(self):
        for channel in self:
            channel.provisioned_state = (
                "provisioned"
                if channel.state in ("provisioned", "effective")
                else "not_provisioned"
            )

    @api.constrains("extension_assignment_id")
    def _check_extension_not_6101(self):
        # codestra.extension.assignment already has a hard database CHECK
        # excluding extension 6101, so no assignment with that value can
        # exist to reach this constraint - this is intentional,
        # unreachable defense-in-depth against that other model's
        # guarantee being weakened later, not independently testable.
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

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            if values.get("state", "requested") != "requested":
                raise ValidationError(
                    _("New channel records must start in the Requested state.")
                )
        return super().create(values_list)

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
        if "state" in values and self.env.context.get(
            "_agent_channel_transition"
        ) is not TRANSITION_CAPABILITY:
            raise AccessError(
                _(
                    "Channel state changes require verified provisioning "
                    "read-back or governed activation, not a direct edit."
                )
            )
        return super().write(values)

    def _apply_step_evidence(
        self,
        verified,
        evidence_hash=None,
        external_id=None,
        provider_reference=None,
        error_code=None,
        error_sanitized=None,
    ):
        """Apply real read-back evidence from a provisioning-service
        callback step to this channel (``email``/``phone`` only - those are
        the only channel types with a corresponding provisioning step
        today). Requires a SHA-256 evidence hash on success.
        """
        self.ensure_one()
        if verified:
            if not evidence_hash or not SHA256_HEX.match(evidence_hash):
                raise ValidationError(
                    _("A verified step requires a SHA-256 evidence hash.")
                )
            values = {
                "state": "provisioned",
                "external_id": external_id,
                "provider_reference": provider_reference,
                "last_verified_at": fields.Datetime.now(),
                "last_error_code": False,
                "last_error_message": False,
            }
        else:
            values = {
                "state": "failed",
                "last_error_code": error_code,
                "last_error_message": error_sanitized,
                "last_verified_at": fields.Datetime.now(),
            }
        self.with_context(_agent_channel_transition=TRANSITION_CAPABILITY).write(
            values
        )

    def _mark_effective(self):
        """Governed transition to ``effective`` for every desired-enabled
        channel in this recordset, called once the owning campaign
        membership is itself fully active and synced (see
        ``codestra.agent.onboarding.action_activate``).
        """
        enabled = self.filtered("desired_enabled")
        if not enabled:
            return
        enabled.with_context(_agent_channel_transition=TRANSITION_CAPABILITY).write(
            {"state": "effective"}
        )


class ProvisioningRequestAgentChannels(models.Model):
    _inherit = "codestra.provisioning.request"

    channel_ids = fields.One2many(
        "codestra.agent.channel", "provisioning_request_id", string="Agent Channels"
    )
