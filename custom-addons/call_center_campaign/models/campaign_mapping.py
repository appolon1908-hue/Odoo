import uuid

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


class CallCenterBusinessUnitIntegrationIdentity(models.Model):
    _inherit = "call.center.business.unit"

    integration_uuid = fields.Char(index=True, copy=False)

    _integration_uuid_unique = models.Constraint(
        "unique(integration_uuid)", "Business-unit integration UUIDs must be unique."
    )


class CrmTeamIntegrationIdentity(models.Model):
    _inherit = "crm.team"

    integration_uuid = fields.Char(index=True, copy=False)

    _integration_uuid_unique = models.Constraint(
        "unique(integration_uuid)", "CRM-team integration UUIDs must be unique."
    )


class CallCenterCampaignIntegrationIdentity(models.Model):
    _inherit = "call.center.campaign"

    integration_uuid = fields.Char(index=True, copy=False)
    telephony_enabled = fields.Boolean(default=False, required=True, tracking=True)
    vicidial_required = fields.Boolean(default=False, required=True, tracking=True)
    vicidial_campaign_id = fields.Char(copy=False, index=True)
    vicidial_user_group = fields.Char(copy=False)
    vicidial_in_group = fields.Char(copy=False)
    extension_pool = fields.Char(copy=False)
    reconciliation_status = fields.Selection(
        [("not_required", "Not Required"), ("pending", "Pending"),
         ("synced_disabled", "Synced Disabled"), ("blocked", "Blocked")],
        default="not_required", required=True, copy=False,
    )
    last_reconciled_at = fields.Datetime(copy=False, readonly=True)
    reconciliation_error = fields.Text(copy=False, readonly=True)

    _integration_uuid_unique = models.Constraint(
        "unique(integration_uuid)", "Campaign integration UUIDs must be unique."
    )
    _vicidial_intent_complete = models.Constraint(
        "CHECK (NOT vicidial_required OR (telephony_enabled AND "
        "vicidial_campaign_id IS NOT NULL AND vicidial_user_group IS NOT NULL))",
        "VICIdial intent requires telephony, a campaign ID, and a user group.",
    )
    _vicidial_inbound_group_required = models.Constraint(
        "CHECK (NOT vicidial_required OR direction NOT IN ('inbound', 'blended') "
        "OR vicidial_in_group IS NOT NULL)",
        "Inbound and blended VICIdial campaigns need an inbound group.",
    )

    @api.constrains(
        "telephony_enabled", "vicidial_required", "vicidial_campaign_id",
        "vicidial_user_group", "vicidial_in_group", "direction",
    )
    def _check_explicit_telephony_intent(self):
        for campaign in self:
            if campaign.vicidial_required and not campaign.telephony_enabled:
                raise ValidationError(
                    "A VICIdial-required campaign must explicitly enable telephony."
                )
            if campaign.vicidial_required and not (
                campaign.vicidial_campaign_id and campaign.vicidial_user_group
            ):
                raise ValidationError(
                    "VICIdial-required campaigns need a campaign ID and user group."
                )
            if (
                campaign.vicidial_required
                and campaign.direction in ("inbound", "blended")
                and not campaign.vicidial_in_group
            ):
                raise ValidationError(
                    "Inbound and blended VICIdial campaigns need an inbound group."
                )


class CallCenterCampaignMapping(models.Model):
    _name = "call.center.campaign.mapping"
    _description = "Inactive cross-system campaign mapping projection"
    _inherit = "call.center.business.unit.mixin"
    _order = "canonical_campaign_code"

    business_record_uuid = fields.Char(
        required=True, index=True, default=lambda self: str(uuid.uuid4()), copy=False
    )
    mapping_uuid = fields.Char(required=True, index=True, copy=False)
    crm_team_id = fields.Many2one("crm.team", required=True, ondelete="restrict", index=True)
    campaign_id = fields.Many2one(
        "call.center.campaign", required=True, ondelete="restrict", index=True
    )
    pipeline_id = fields.Many2one(
        "call.center.pipeline", required=True, ondelete="restrict", index=True
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        ondelete="restrict",
        index=True,
    )
    canonical_campaign_code = fields.Char(required=True, index=True)
    vicidial_campaign_id = fields.Char(required=True, index=True)
    direction = fields.Selection(
        [("IN", "Inbound"), ("OUT", "Outbound")], required=True
    )
    environment = fields.Selection(
        [("development", "Development"), ("staging", "Staging"), ("production", "Production")],
        required=True,
        default="staging",
        index=True,
    )
    n8n_scope = fields.Char(required=True)
    schema_version = fields.Integer(required=True, default=1)
    mapping_version = fields.Integer(required=True, default=1)
    desired_state = fields.Selection(
        [("inactive", "Inactive"), ("active", "Active")],
        required=True,
        default="inactive",
    )
    desired_state_hash = fields.Char(required=True, size=64)
    observed_state = fields.Selection(
        [("not_observed", "Not Observed"), ("confirmed", "Confirmed")],
        required=True,
        default="not_observed",
    )
    observed_state_hash = fields.Char(size=64, copy=False)
    last_applied_at = fields.Datetime(copy=False)
    last_read_back_at = fields.Datetime(copy=False)
    drift_status = fields.Selection(
        [
            ("not_observed", "Not Observed"),
            ("in_sync", "In Sync"),
            ("drifted", "Drifted"),
            ("blocked_missing_odoo_reference", "Blocked Missing Odoo Reference"),
        ],
        required=True,
        default="not_observed",
    )
    production_eligible = fields.Boolean(default=False, required=True)
    activation_mode = fields.Selection(
        [("DISABLED", "Disabled"), ("CANARY_ONLY", "Canary Only"), ("FULL", "Full")],
        default="DISABLED", required=True, index=True,
    )
    active = fields.Boolean(default=False, required=True)

    _mapping_uuid_unique = models.Constraint(
        "unique(mapping_uuid)", "Mapping UUIDs must be unique."
    )
    _canonical_environment_unique = models.Constraint(
        "unique(environment, canonical_campaign_code)",
        "Canonical campaign codes must be unique per environment.",
    )
    _physical_id_unique = models.Constraint(
        "unique(vicidial_campaign_id)", "Physical VICIdial campaign IDs must be unique."
    )
    _business_record_uuid_unique = models.Constraint(
        "unique(business_record_uuid)", "Business record UUIDs must be unique."
    )
    _version_positive = models.Constraint(
        "check(schema_version > 0 AND mapping_version > 0)",
        "Schema and mapping versions must be positive.",
    )

    @api.model
    def _ensure_projection_integration_uuids(self):
        """Assign stable cross-system identities without inventing ownership."""
        namespace = uuid.UUID("498af626-1567-56c4-9580-983a66cc74ca")
        mappings = self.with_context(active_test=False).search(
            [("environment", "=", "staging")]
        )
        for mapping in mappings:
            unit = mapping.business_unit_id
            team = mapping.crm_team_id
            campaign = mapping.campaign_id
            if not unit.integration_uuid:
                unit.integration_uuid = str(
                    uuid.uuid5(namespace, f"odoo-business-unit:{unit.code}")
                )
            if not team.integration_uuid:
                team.integration_uuid = str(
                    uuid.uuid5(namespace, f"odoo-crm-team:{unit.code}:{team.id}")
                )
            if not campaign.integration_uuid:
                campaign._write_integration_state(
                    {
                        "integration_uuid": str(
                            uuid.uuid5(
                                namespace,
                                f"odoo-campaign:{mapping.environment}:{campaign.code}",
                            )
                        )
                    }
                )
        return True

    @api.constrains(
        "business_unit_id",
        "crm_team_id",
        "campaign_id",
        "pipeline_id",
        "canonical_campaign_code",
        "environment",
        "production_eligible",
        "activation_mode",
        "active",
        "desired_state",
        "observed_state",
        "observed_state_hash",
        "last_read_back_at",
    )
    def _check_projection_scope(self):
        for mapping in self:
            if mapping.campaign_id.business_unit_id != mapping.business_unit_id:
                raise ValidationError("Mapping campaign and business unit must match.")
            if mapping.crm_team_id.business_unit_id != mapping.business_unit_id:
                raise ValidationError("Mapping CRM team and business unit must match.")
            if mapping.pipeline_id.business_unit_id != mapping.business_unit_id:
                raise ValidationError("Mapping pipeline and business unit must match.")
            if mapping.company_id != mapping.business_unit_id.company_id:
                raise ValidationError("Mapping company and business unit company must match.")
            if mapping.canonical_campaign_code != mapping.campaign_id.code:
                raise ValidationError("Mapping canonical code must equal the campaign code.")
            if mapping.environment == "production" or mapping.production_eligible:
                if not (mapping.environment == "production" and mapping.production_eligible
                        and mapping.activation_mode == "CANARY_ONLY"):
                    raise ValidationError("Production mapping requires explicit canary-only approval.")
            if mapping.activation_mode == "FULL":
                raise ValidationError("Full production activation is outside this projection contract.")
            if mapping.active or mapping.desired_state != "inactive":
                raise ValidationError("Canary mappings must remain inactive for unrestricted traffic.")
            if mapping.observed_state == "confirmed" and (
                not mapping.observed_state_hash or not mapping.last_read_back_at
            ):
                raise ValidationError("Confirmed observed state requires authoritative read-back.")

    def write(self, vals):
        if "mapping_version" in vals:
            for mapping in self:
                if vals["mapping_version"] < mapping.mapping_version:
                    raise ValidationError("Mapping version cannot decrease.")
        protected = {"mapping_uuid", "canonical_campaign_code", "vicidial_campaign_id"}
        if protected & vals.keys() and not self.env.user.has_group(
            "call_center_core.group_call_center_admin"
        ):
            raise AccessError("Only call-center administrators may change mapping identity.")
        return super().write(vals)

    def export_data(self, fields_to_export):
        if not self.env.user.has_group("call_center_core.group_call_center_manager"):
            raise AccessError("Campaign mapping export is restricted.")
        return super().export_data(fields_to_export)
