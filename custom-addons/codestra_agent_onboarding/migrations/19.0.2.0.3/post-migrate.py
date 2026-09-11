import logging

from odoo import SUPERUSER_ID, api

from odoo.addons.codestra_agent_onboarding.models.agent_channel import (
    CHANNEL_TRANSITION_CAPABILITY,
)

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    Membership = env["cc.campaign.membership"]
    Channel = env["codestra.agent.channel"]
    for membership in Membership.with_context(active_test=False).search([]):
        campaign = membership.campaign_id
        supervisor_membership = campaign.primary_supervisor_membership_id
        supervisor = (
            supervisor_membership.user_id if supervisor_membership else False
        )
        if not supervisor:
            supervisor = campaign.legacy_campaign_id.supervisor_ids[:1]
        if not supervisor:
            _logger.warning(
                "Skipping agent-channel migration for membership %s: "
                "campaign has no approved supervisor",
                membership.id,
            )
            continue

        request = env["codestra.provisioning.request"].search(
            [("cc_membership_id", "=", membership.id)],
            order="id desc",
            limit=1,
        )
        desired = {
            "email": bool(membership.campaign_email_identity),
            "sms": bool(getattr(membership, "sms_enabled", False)),
            "phone": bool(getattr(membership, "extension", False)),
            "webrtc": bool(getattr(membership, "webrtc_enabled", False)),
        }
        matched = bool(
            membership.state == "active"
            and membership.last_sync_status == "matched"
            and membership.read_back_evidence
        )
        state = "requested"
        if matched and not any(desired.values()):
            state = "disabled"
        elif matched:
            state = "effective" if membership.user_id.active else "provisioned"

        for channel_type, enabled in desired.items():
            if Channel.search_count([
                ("membership_id", "=", membership.id),
                ("channel_type", "=", channel_type),
            ]):
                continue
            channel = Channel.create({
                "employee_id": membership.employee_id.id,
                "campaign_id": campaign.id,
                "membership_id": membership.id,
                "provisioning_request_id": request.id if request else False,
                "supervisor_id": supervisor.id,
                "channel_type": channel_type,
                "desired_enabled": enabled,
                "incoming_allowed": (
                    bool(getattr(membership, "incoming_calls_enabled", False))
                    if channel_type in {"phone", "webrtc"} else False
                ),
                "outgoing_allowed": (
                    bool(getattr(membership, "outgoing_calls_enabled", False))
                    if channel_type in {"phone", "webrtc"} else False
                ),
            })
            if state != "requested":
                channel.with_context(
                    _codestra_agent_channel_transition=CHANNEL_TRANSITION_CAPABILITY
                ).write({"state": state})
