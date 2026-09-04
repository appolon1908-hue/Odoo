from odoo import _, models
from odoo.exceptions import ValidationError


class CodestraAgentOnboardingVicidialBinding(models.Model):
    _inherit = "codestra.agent.onboarding"

    def _assert_assignment_ready(self):
        result = super()._assert_assignment_ready()
        for record in self.filtered("needs_vicidial"):
            campaign = record.campaign_id.legacy_campaign_id
            missing = []
            if not campaign.telephony_enabled:
                missing.append(_("telephony enablement"))
            if not campaign.vicidial_required:
                missing.append(_("VICIdial requirement"))
            if not campaign.vicidial_campaign_id:
                missing.append(_("native VICIdial campaign ID"))
            if not campaign.vicidial_user_group:
                missing.append(_("campaign VICIdial user group"))
            if campaign.reconciliation_status != "synced_disabled":
                missing.append(_("disabled-state reconciliation"))
            if (
                campaign.direction in {"inbound", "blended"}
                and not campaign.vicidial_in_group
            ):
                missing.append(_("VICIdial inbound group"))
            if missing:
                raise ValidationError(
                    _("Complete the governed VICIdial binding: %s")
                    % ", ".join(missing)
                )
            if (
                record.role_template_id.vicidial_user_group
                != campaign.vicidial_user_group
            ):
                raise ValidationError(
                    _(
                        "The role-template VICIdial group must match the "
                        "campaign's approved group."
                    )
                )
        return result

    def _event_context(self):
        self.ensure_one()
        result = super()._event_context()
        campaign = self.campaign_id.legacy_campaign_id
        result.update(
            {
                "employee_display_name": self.employee_id.name,
                "vicidial_campaign_id": (
                    campaign.vicidial_campaign_id
                    if self.needs_vicidial
                    else False
                ),
                "vicidial_user_group": (
                    self.role_template_id.vicidial_user_group
                    if self.needs_vicidial
                    else False
                ),
                "vicidial_inbound_groups": (
                    [campaign.vicidial_in_group]
                    if self.needs_vicidial and campaign.vicidial_in_group
                    else []
                ),
            }
        )
        return result
