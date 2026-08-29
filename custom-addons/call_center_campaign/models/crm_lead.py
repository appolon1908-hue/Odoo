from odoo import api, fields, models
from odoo.exceptions import ValidationError


class CrmLead(models.Model):
    _inherit = "crm.lead"

    call_center_campaign_id = fields.Many2one(
        "call.center.campaign",
        index=True,
        tracking=True,
        ondelete="restrict",
        help="Required only when this record is managed by the Codestra call-center workflow.",
    )
    is_codestra_call_center_lead = fields.Boolean(
        string="Codestra Call Center Lead",
        default=False,
        index=True,
        tracking=True,
        help="Explicitly classifies records governed by Codestra campaign controls.",
    )
    campaign_remediation_status = fields.Selection(
        [
            ("not_required", "Not Required"),
            ("valid", "Valid"),
            ("review", "Campaign Review Required"),
        ],
        default="not_required",
        required=True,
        index=True,
        copy=False,
    )
    call_center_department_id = fields.Many2one(
        "call.center.department", ondelete="restrict", index=True, tracking=True
    )
    call_center_operational_team_id = fields.Many2one(
        "call.center.team", ondelete="restrict", index=True, tracking=True
    )
    call_center_supervisor_id = fields.Many2one(
        "res.users", ondelete="restrict", index=True, tracking=True
    )
    call_center_manager_id = fields.Many2one(
        "res.users", ondelete="restrict", index=True, tracking=True
    )
    lifecycle_reason = fields.Char(tracking=True)
    related_call_reference = fields.Char()
    lifecycle_next_action = fields.Char(tracking=True)

    @api.constrains(
        "business_unit_id",
        "is_codestra_call_center_lead",
        "call_center_campaign_id",
        "team_id",
        "call_center_department_id",
        "call_center_operational_team_id",
        "call_center_supervisor_id",
        "call_center_manager_id",
        "user_id",
    )
    def _check_operational_scope(self):
        for lead in self:
            if lead.is_codestra_call_center_lead and not lead.call_center_campaign_id:
                raise ValidationError(
                    "A Codestra-managed CRM lead requires a valid call-center campaign."
                )
            if (
                lead.call_center_campaign_id
                and lead.call_center_campaign_id.business_unit_id
                != lead.business_unit_id
            ):
                raise ValidationError(
                    "A lead campaign must belong to the lead business unit."
                )
            if (
                lead.team_id
                and lead.team_id.business_unit_id
                and lead.team_id.business_unit_id != lead.business_unit_id
            ):
                raise ValidationError(
                    "A lead CRM team must belong to the lead business unit."
                )
            for record, label in (
                (lead.call_center_department_id, "department"),
                (lead.call_center_operational_team_id, "operational team"),
            ):
                if record and record.business_unit_id != lead.business_unit_id:
                    raise ValidationError(
                        f"A lead {label} must belong to the lead business unit."
                    )
            for user, label in (
                (lead.user_id, "assigned agent"),
                (lead.call_center_supervisor_id, "supervisor"),
                (lead.call_center_manager_id, "manager"),
            ):
                if (
                    user
                    and user.call_center_business_unit_ids
                    and lead.business_unit_id
                    not in user.call_center_business_unit_ids
                ):
                    raise ValidationError(
                        f"A lead {label} must be authorized for the lead business unit."
                    )

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if values.get("is_codestra_call_center_lead") and not values.get(
                "call_center_campaign_id"
            ):
                raise ValidationError(
                    "Codestra lead creation failed: no campaign mapping was supplied."
                )
            if values.get("is_codestra_call_center_lead"):
                values.setdefault("campaign_remediation_status", "valid")
        return super().create(vals_list)

    def write(self, vals):
        for lead in self:
            managed = vals.get(
                "is_codestra_call_center_lead", lead.is_codestra_call_center_lead
            )
            campaign = vals.get(
                "call_center_campaign_id", lead.call_center_campaign_id.id
            )
            if managed and not campaign:
                raise ValidationError(
                    "Codestra lead update failed: a call-center campaign is required."
                )
        if vals.get("is_codestra_call_center_lead"):
            vals.setdefault("campaign_remediation_status", "valid")
        old_stages = {lead.id: lead.stage_id.id for lead in self}
        result = super().write(vals)
        if "stage_id" in vals:
            for lead in self:
                self.env["call.center.audit.event"].sudo().create(
                    {
                        "business_unit_id": lead.business_unit_id.id,
                        "event_type": "lead.stage.changed",
                        "model_name": lead._name,
                        "record_id": lead.id,
                        "reason": vals.get("lifecycle_reason") or lead.lifecycle_reason,
                        "previous_values_json": {"stage_id": old_stages[lead.id]},
                        "new_values_json": {"stage_id": lead.stage_id.id},
                    }
                )
        return result
