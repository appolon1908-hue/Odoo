from odoo import api, fields, models


class CodestraPlatformUserDashboard(models.Model):
    """Cross-module Super Admin status rollup for codestra.platform.user.

    codestra.agent.channel and cc.campaign.membership.platform_user_id both
    live in this module (codestra_agent_onboarding), which depends on
    codestra_identity_provisioning - not the reverse - so this compute
    logic cannot live on the base codestra.platform.user model itself
    without creating a circular module dependency. Extending the model
    here, in the module that actually owns both halves of the join, is the
    correct place for it.
    """

    _inherit = "codestra.platform.user"

    membership_ids = fields.One2many(
        "cc.campaign.membership", "platform_user_id", string="Campaign Memberships"
    )

    channel_status_email = fields.Selection(
        [("effective", "Effective"), ("pending", "Pending"), ("off", "Off")],
        compute="_compute_channel_statuses",
    )
    channel_status_sms = fields.Selection(
        [("effective", "Effective"), ("pending", "Pending"), ("off", "Off")],
        compute="_compute_channel_statuses",
    )
    channel_status_phone = fields.Selection(
        [("effective", "Effective"), ("pending", "Pending"), ("off", "Off")],
        compute="_compute_channel_statuses",
    )
    channel_status_webrtc = fields.Selection(
        [("effective", "Effective"), ("pending", "Pending"), ("off", "Off")],
        compute="_compute_channel_statuses",
    )
    provisioning_drift_status = fields.Selection(
        [("matched", "Matched"), ("drift", "Drift"), ("unknown", "Unknown")],
        compute="_compute_provisioning_drift_status",
        help="Compares codestra.agent.channel's requested_state against "
        "provisioned_state across every channel linked through this "
        "user's campaign memberships - the same desired/observed "
        "separation the channel model itself enforces, rolled up to one "
        "platform-user-level signal for the Super Admin status view.",
    )

    def _channels(self):
        """Every codestra.agent.channel reachable through this platform
        user's campaign memberships. codestra.agent.channel links by
        employee_id, not platform_user_id directly, so this goes through
        membership_ids first - the same path every compute below needs,
        kept in one place rather than duplicated per compute.
        """
        self.ensure_one()
        employees = self.membership_ids.employee_id
        if not employees:
            return self.env["codestra.agent.channel"]
        return self.env["codestra.agent.channel"].search(
            [("employee_id", "in", employees.ids)]
        )

    @api.depends(
        "membership_ids.employee_id",
        "membership_ids.channel_ids.channel_type",
        "membership_ids.channel_ids.effective_access",
        "membership_ids.channel_ids.desired_enabled",
    )
    def _compute_channel_statuses(self):
        for record in self:
            channels = record._channels()
            for channel_type, field_name in (
                ("email", "channel_status_email"),
                ("sms", "channel_status_sms"),
                ("phone", "channel_status_phone"),
                ("webrtc", "channel_status_webrtc"),
            ):
                rows = channels.filtered(lambda c, t=channel_type: c.channel_type == t)
                if not rows or not any(rows.mapped("desired_enabled")):
                    record[field_name] = "off"
                elif all(rows.mapped("effective_access")):
                    record[field_name] = "effective"
                else:
                    record[field_name] = "pending"

    @api.depends(
        "membership_ids.channel_ids.requested_state",
        "membership_ids.channel_ids.provisioned_state",
    )
    def _compute_provisioning_drift_status(self):
        for record in self:
            channels = record._channels()
            if not channels:
                record.provisioning_drift_status = "unknown"
                continue
            matched = all(
                (channel.requested_state == "requested")
                == (channel.provisioned_state == "provisioned")
                for channel in channels
            )
            record.provisioning_drift_status = "matched" if matched else "drift"
