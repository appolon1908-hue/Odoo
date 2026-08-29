import hashlib
import json
import re
import uuid

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


CANONICAL_CODE = re.compile(r"^[A-Z0-9]+(?:-[A-Z0-9]+)*$")
ADOPTION_NAMESPACE = uuid.UUID("43f9b0cc-6810-5f91-a13d-e11733e63dcf")

CAMPAIGN_LIFECYCLE = [
    ("draft", "Draft"),
    ("design_pending", "Design Pending"),
    ("design_ready", "Design Ready"),
    ("approval_pending", "Approval Pending"),
    ("approved", "Approved"),
    ("provisioning", "Provisioning"),
    ("provisioned_disabled", "Provisioned Disabled"),
    ("testing", "Testing"),
    ("staging_ready", "Staging Ready"),
    ("activation_pending", "Activation Pending"),
    ("active", "Active"),
    ("blocked", "Blocked"),
    ("failed", "Failed"),
    ("rollback_pending", "Rollback Pending"),
    ("rolled_back", "Rolled Back"),
    ("archived", "Archived"),
]

SAFE_LIFECYCLE_TRANSITIONS = {
    "draft": {"design_pending", "blocked", "archived"},
    "design_pending": {"design_ready", "failed", "blocked", "archived"},
    "design_ready": {"approval_pending", "draft", "blocked", "archived"},
    "approval_pending": {"approved", "design_ready", "blocked", "archived"},
    "approved": {"provisioning", "design_ready", "blocked", "archived"},
    "provisioning": {"provisioned_disabled", "failed", "rollback_pending"},
    "provisioned_disabled": {"testing", "rollback_pending", "blocked", "archived"},
    "testing": {"staging_ready", "failed", "rollback_pending", "blocked"},
    "staging_ready": {"activation_pending", "testing", "blocked", "archived"},
    "activation_pending": {"staging_ready", "blocked", "archived"},
    "blocked": {"draft", "design_pending", "rollback_pending", "archived"},
    "failed": {"draft", "rollback_pending", "archived"},
    "rollback_pending": {"rolled_back", "failed"},
    "rolled_back": {"draft", "archived"},
    "archived": set(),
    "active": {"blocked", "rollback_pending", "archived"},
}


def _canonical_code(value):
    return (value or "").strip().upper()


class CcBusinessUnit(models.Model):
    _name = "cc.business.unit"
    _description = "Canonical Contact Center Business Unit"
    _inherits = {"call.center.business.unit": "legacy_business_unit_id"}
    _order = "sequence, name"

    legacy_business_unit_id = fields.Many2one(
        "call.center.business.unit",
        required=True,
        ondelete="restrict",
        index=True,
        copy=False,
    )
    scope_uuid = fields.Char(
        required=True,
        index=True,
        copy=False,
        default=lambda self: str(uuid.uuid4()),
    )
    campaign_ids = fields.One2many("cc.campaign", "cc_business_unit_id")

    _legacy_business_unit_unique = models.Constraint(
        "unique(legacy_business_unit_id)",
        "A legacy business unit may have only one canonical scope.",
    )
    _scope_uuid_unique = models.Constraint(
        "unique(scope_uuid)", "Business-unit scope UUIDs must be unique."
    )

    @api.model_create_multi
    def create(self, values_list):
        prepared = []
        for original in values_list:
            values = dict(original)
            if values.get("code"):
                values["code"] = _canonical_code(values["code"])
            if not values.get("legacy_business_unit_id"):
                values.setdefault("active", False)
            prepared.append(values)
        return super(CcBusinessUnit, self.with_context(cc_skip_auto_adoption=True)).create(
            prepared
        )

    @api.constrains("code")
    def _check_canonical_code(self):
        for unit in self:
            if not CANONICAL_CODE.fullmatch(unit.code or ""):
                raise ValidationError(
                    _("Business-unit codes must use uppercase letters and digits.")
                )

    def write(self, values):
        if "legacy_business_unit_id" in values and any(
            unit.legacy_business_unit_id.id != values["legacy_business_unit_id"]
            for unit in self
        ):
            raise AccessError(_("The adopted business-unit record is immutable."))
        return super().write(values)

    @api.model
    def _adopt_legacy_records(self):
        """Create one idempotent canonical wrapper for each existing owner."""
        LegacyUnit = self.env["call.center.business.unit"].with_context(
            active_test=False
        )
        CanonicalUnit = self.with_context(active_test=False)
        existing_unit_ids = set(
            CanonicalUnit.search([]).mapped("legacy_business_unit_id").ids
        )
        for legacy_unit in LegacyUnit.search([]):
            if legacy_unit.id in existing_unit_ids:
                continue
            CanonicalUnit.create(
                {
                    "legacy_business_unit_id": legacy_unit.id,
                    "scope_uuid": str(
                        uuid.uuid5(
                            ADOPTION_NAMESPACE,
                            f"business-unit:{legacy_unit.code}:{legacy_unit.id}",
                        )
                    ),
                }
            )

        Campaign = self.env["cc.campaign"].with_context(active_test=False)
        LegacyCampaign = self.env["call.center.campaign"].with_context(
            active_test=False
        )
        unit_by_legacy_id = {
            unit.legacy_business_unit_id.id: unit
            for unit in CanonicalUnit.search([])
        }
        existing_campaign_ids = set(
            Campaign.search([]).mapped("legacy_campaign_id").ids
        )
        for legacy_campaign in LegacyCampaign.search([]):
            if legacy_campaign.id in existing_campaign_ids:
                continue
            canonical_unit = unit_by_legacy_id.get(legacy_campaign.business_unit_id.id)
            if not canonical_unit:
                raise ValidationError(
                    _("Campaign adoption requires an adopted business unit.")
                )
            lifecycle = {
                "approved": "approved",
                "closed": "archived",
                "active": "blocked",
                "paused": "blocked",
            }.get(legacy_campaign.state, "draft")
            identifier_status = (
                "canonical"
                if CANONICAL_CODE.fullmatch(legacy_campaign.code or "")
                else "legacy_exception"
            )
            if identifier_status == "legacy_exception":
                lifecycle = "blocked"
            Campaign.create(
                {
                    "legacy_campaign_id": legacy_campaign.id,
                    "cc_business_unit_id": canonical_unit.id,
                    "workspace_uuid": str(
                        uuid.uuid5(
                            ADOPTION_NAMESPACE,
                            f"campaign:{legacy_campaign.code}:{legacy_campaign.id}",
                        )
                    ),
                    "lifecycle_state": lifecycle,
                    "identifier_status": identifier_status,
                }
            )

        Channel = self.env["cc.campaign.channel"].with_context(active_test=False)
        Mapping = self.env["call.center.campaign.mapping"].with_context(
            active_test=False
        )
        campaign_by_legacy_id = {
            campaign.legacy_campaign_id.id: campaign for campaign in Campaign.search([])
        }
        existing_mapping_ids = set(Channel.search([]).mapped("legacy_mapping_id").ids)
        for mapping in Mapping.search([]):
            if mapping.id in existing_mapping_ids:
                continue
            campaign = campaign_by_legacy_id.get(mapping.campaign_id.id)
            if not campaign:
                raise ValidationError(_("Channel adoption requires an adopted campaign."))
            callback_compatibility = mapping.canonical_campaign_code.endswith(
                "-CALLBACK-OUT"
            )
            Channel.create(
                {
                    "campaign_id": campaign.id,
                    "name": mapping.canonical_campaign_code,
                    "code": mapping.canonical_campaign_code,
                    "direction": (
                        "inbound" if mapping.direction == "IN" else "outbound"
                    ),
                    "technical_callback_compatibility": callback_compatibility,
                    "agent_login_allowed": not callback_compatibility,
                    "legacy_mapping_id": mapping.id,
                    "identifier_status": (
                        "canonical"
                        if CANONICAL_CODE.fullmatch(
                            mapping.canonical_campaign_code or ""
                        )
                        else "legacy_exception"
                    ),
                    "active": False,
                }
            )
        return {
            "business_units": CanonicalUnit.search_count([]),
            "campaigns": Campaign.search_count([]),
            "channels": Channel.search_count([]),
        }


class CcCampaign(models.Model):
    _name = "cc.campaign"
    _description = "Canonical Contact Center Campaign Workspace"
    _inherits = {"call.center.campaign": "legacy_campaign_id"}
    _order = "cc_business_unit_id, code"

    legacy_campaign_id = fields.Many2one(
        "call.center.campaign",
        required=True,
        ondelete="restrict",
        index=True,
        copy=False,
    )
    cc_business_unit_id = fields.Many2one(
        "cc.business.unit", required=True, ondelete="restrict", index=True
    )
    workspace_uuid = fields.Char(
        required=True,
        index=True,
        copy=False,
        default=lambda self: str(uuid.uuid4()),
    )
    environment = fields.Selection(
        [
            ("development", "Development"),
            ("staging", "Staging"),
            ("production", "Production"),
        ],
        required=True,
        default="staging",
        index=True,
    )
    lifecycle_state = fields.Selection(
        CAMPAIGN_LIFECYCLE,
        required=True,
        default="draft",
        index=True,
        copy=False,
    )
    identifier_status = fields.Selection(
        [
            ("canonical", "Canonical"),
            ("legacy_exception", "Blocked Legacy Exception"),
        ],
        required=True,
        default="canonical",
        index=True,
        copy=False,
    )
    is_human_staffed = fields.Boolean(default=True, required=True)
    production_eligible = fields.Boolean(default=False, required=True, copy=False)
    live_enabled = fields.Boolean(default=False, required=True, copy=False)
    scope_version = fields.Integer(default=1, required=True, copy=False)
    channel_ids = fields.One2many("cc.campaign.channel", "campaign_id")
    policy_ids = fields.One2many("cc.campaign.policy", "campaign_id")

    _legacy_campaign_unique = models.Constraint(
        "unique(legacy_campaign_id)",
        "A legacy campaign may have only one canonical workspace.",
    )
    _workspace_uuid_unique = models.Constraint(
        "unique(workspace_uuid)", "Campaign workspace UUIDs must be unique."
    )
    _scope_version_positive = models.Constraint(
        "check(scope_version > 0)", "Campaign scope versions must be positive."
    )

    @api.model_create_multi
    def create(self, values_list):
        prepared = []
        Unit = self.env["cc.business.unit"].with_context(active_test=False)
        LegacyCampaign = self.env["call.center.campaign"].with_context(
            active_test=False
        )
        for original in values_list:
            values = dict(original)
            legacy_campaign = LegacyCampaign.browse(values.get("legacy_campaign_id"))
            canonical_unit = Unit.browse(values.get("cc_business_unit_id"))
            if legacy_campaign.exists() and not canonical_unit.exists():
                canonical_unit = Unit.search(
                    [
                        (
                            "legacy_business_unit_id",
                            "=",
                            legacy_campaign.business_unit_id.id,
                        )
                    ],
                    limit=1,
                )
                values["cc_business_unit_id"] = canonical_unit.id
            if canonical_unit.exists():
                values.setdefault(
                    "business_unit_id", canonical_unit.legacy_business_unit_id.id
                )
            if values.get("code"):
                values["code"] = _canonical_code(values["code"])
            if not legacy_campaign.exists():
                values.setdefault("active", False)
                values.setdefault("state", "draft")
                values.setdefault("telephony_enabled", False)
                values.setdefault("vicidial_required", False)
            prepared.append(values)
        return super(CcCampaign, self.with_context(cc_skip_auto_adoption=True)).create(
            prepared
        )

    @api.constrains(
        "legacy_campaign_id",
        "cc_business_unit_id",
        "code",
        "identifier_status",
        "live_enabled",
        "production_eligible",
        "lifecycle_state",
    )
    def _check_workspace(self):
        for campaign in self:
            if (
                campaign.legacy_campaign_id.business_unit_id
                != campaign.cc_business_unit_id.legacy_business_unit_id
            ):
                raise ValidationError(
                    _("Canonical and legacy campaign business units must match.")
                )
            if campaign.identifier_status == "canonical" and not CANONICAL_CODE.fullmatch(
                campaign.code or ""
            ):
                raise ValidationError(
                    _("Campaign codes must use uppercase hyphenated identifiers.")
                )
            if (
                campaign.identifier_status == "legacy_exception"
                and campaign.lifecycle_state != "blocked"
            ):
                raise ValidationError(
                    _("Legacy identifier exceptions must remain blocked.")
                )
            if (
                campaign.live_enabled
                or campaign.production_eligible
                or campaign.lifecycle_state == "active"
            ):
                raise ValidationError(
                    _(
                        "This staging implementation cannot enable production or "
                        "an active campaign."
                    )
                )

    def write(self, values):
        immutable = {"legacy_campaign_id", "cc_business_unit_id", "workspace_uuid"}
        changing = immutable & values.keys()
        if changing and not self.env.context.get("cc_scope_migration"):
            for campaign in self:
                for field_name in changing:
                    current = campaign[field_name]
                    current_value = (
                        current.id
                        if campaign._fields[field_name].type == "many2one"
                        else current
                    )
                    if current_value != values[field_name]:
                        raise AccessError(
                            _("Campaign ownership and workspace identity are immutable.")
                        )
        return super().write(values)

    def transition_to(self, target_state):
        if not self.env.user.has_group("call_center_core.group_call_center_manager"):
            raise AccessError(_("Only contact-center managers may change lifecycle."))
        if target_state == "active":
            raise ValidationError(
                _("Production activation is not available in the staging core.")
            )
        valid_states = {key for key, _label in CAMPAIGN_LIFECYCLE}
        if target_state not in valid_states:
            raise ValidationError(_("Unknown campaign lifecycle state."))
        for campaign in self:
            if target_state not in SAFE_LIFECYCLE_TRANSITIONS[campaign.lifecycle_state]:
                raise ValidationError(
                    _(
                        "Campaign lifecycle transition from %(source)s to %(target)s "
                        "is not allowed.",
                        source=campaign.lifecycle_state,
                        target=target_state,
                    )
                )
        self.write({"lifecycle_state": target_state})
        return True


class CcCampaignScopedMixin(models.AbstractModel):
    _name = "cc.campaign.scoped.mixin"
    _description = "Immutable Campaign-Scoped Record"
    _abstract = True

    campaign_id = fields.Many2one(
        "cc.campaign", required=True, ondelete="restrict", index=True
    )
    business_unit_id = fields.Many2one(
        "cc.business.unit",
        related="campaign_id.cc_business_unit_id",
        store=True,
        readonly=True,
        index=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="campaign_id.cc_business_unit_id.company_id",
        store=True,
        readonly=True,
        index=True,
    )
    campaign_scope_version = fields.Integer(
        related="campaign_id.scope_version", store=True, readonly=True
    )

    def write(self, values):
        if "campaign_id" in values and not self.env.context.get("cc_scope_migration"):
            if any(record.campaign_id.id != values["campaign_id"] for record in self):
                raise AccessError(_("Campaign ownership is immutable."))
        return super().write(values)


class CcCampaignChannel(models.Model):
    _name = "cc.campaign.channel"
    _description = "Campaign Workspace Channel"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "campaign_id, direction, code"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    direction = fields.Selection(
        [
            ("inbound", "Inbound"),
            ("outbound", "Outbound"),
            ("blended", "Blended"),
        ],
        required=True,
        index=True,
    )
    technical_callback_compatibility = fields.Boolean(
        default=False, required=True, index=True
    )
    agent_login_allowed = fields.Boolean(default=True, required=True)
    active = fields.Boolean(default=False, required=True)
    identifier_status = fields.Selection(
        [
            ("canonical", "Canonical"),
            ("legacy_exception", "Blocked Legacy Exception"),
        ],
        required=True,
        default="canonical",
        index=True,
        copy=False,
    )
    legacy_mapping_id = fields.Many2one(
        "call.center.campaign.mapping",
        ondelete="restrict",
        index=True,
        copy=False,
    )

    _campaign_channel_code_unique = models.Constraint(
        "unique(campaign_id, code)",
        "Channel codes must be unique inside a campaign workspace.",
    )
    _legacy_mapping_unique = models.Constraint(
        "unique(legacy_mapping_id)",
        "A legacy mapping may be adopted by only one campaign channel.",
    )

    @api.model_create_multi
    def create(self, values_list):
        prepared = []
        for original in values_list:
            values = dict(original)
            if values.get("code"):
                values["code"] = _canonical_code(values["code"])
            if values.get("technical_callback_compatibility"):
                values["agent_login_allowed"] = False
                values["active"] = False
            prepared.append(values)
        return super().create(prepared)

    @api.constrains(
        "campaign_id",
        "code",
        "identifier_status",
        "direction",
        "technical_callback_compatibility",
        "agent_login_allowed",
        "active",
        "legacy_mapping_id",
    )
    def _check_channel(self):
        for channel in self:
            if channel.identifier_status == "canonical" and not CANONICAL_CODE.fullmatch(
                channel.code or ""
            ):
                raise ValidationError(
                    _("Channel codes must use uppercase hyphenated identifiers.")
                )
            if channel.identifier_status == "legacy_exception" and channel.active:
                raise ValidationError(
                    _("Legacy identifier exceptions must remain disabled.")
                )
            if channel.technical_callback_compatibility and (
                channel.agent_login_allowed or channel.active
            ):
                raise ValidationError(
                    _("Callback compatibility channels must remain disabled for login.")
                )
            mapping = channel.legacy_mapping_id
            if mapping:
                expected_direction = (
                    "inbound" if mapping.direction == "IN" else "outbound"
                )
                if mapping.campaign_id != channel.campaign_id.legacy_campaign_id:
                    raise ValidationError(
                        _("The adopted mapping must belong to the same campaign.")
                    )
                if mapping.canonical_campaign_code != channel.code:
                    raise ValidationError(
                        _("Channel code must equal the adopted canonical mapping code.")
                    )
                if channel.direction != expected_direction:
                    raise ValidationError(
                        _("Channel direction must equal the adopted mapping direction.")
                    )

    def write(self, values):
        if "legacy_mapping_id" in values and not self.env.context.get(
            "cc_scope_migration"
        ):
            if any(
                channel.legacy_mapping_id.id != values["legacy_mapping_id"]
                for channel in self
            ):
                raise AccessError(_("The adopted channel mapping is immutable."))
        return super().write(values)


class CcCampaignPolicy(models.Model):
    _name = "cc.campaign.policy"
    _description = "Versioned Campaign Workspace Policy"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "campaign_id, policy_type, version desc"

    name = fields.Char(required=True)
    policy_type = fields.Selection(
        [
            ("recording", "Recording"),
            ("callback", "Callback"),
            ("email", "Email"),
            ("quality", "Quality"),
            ("wfm", "Workforce Management"),
            ("compliance", "Compliance"),
            ("calling_hours", "Calling Hours"),
            ("transfer", "Transfer"),
        ],
        required=True,
        index=True,
    )
    version = fields.Integer(required=True, default=1)
    state = fields.Selection(
        [("draft", "Draft"), ("approved", "Approved"), ("retired", "Retired")],
        required=True,
        default="draft",
        index=True,
        copy=False,
    )
    effective_from = fields.Datetime()
    effective_to = fields.Datetime()
    settings_json = fields.Json(required=True, default=dict)
    policy_hash = fields.Char(
        compute="_compute_policy_hash", store=True, readonly=True, index=True
    )

    _campaign_policy_version_unique = models.Constraint(
        "unique(campaign_id, policy_type, version)",
        "Policy versions must be unique by campaign and policy type.",
    )
    _positive_version = models.Constraint(
        "check(version > 0)", "Policy versions must be positive."
    )

    @api.depends("campaign_id", "policy_type", "version", "settings_json")
    def _compute_policy_hash(self):
        for policy in self:
            payload = {
                "campaign_uuid": policy.campaign_id.workspace_uuid,
                "policy_type": policy.policy_type,
                "version": policy.version,
                "settings": policy.settings_json or {},
            }
            encoded = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), default=str
            ).encode("utf-8")
            policy.policy_hash = hashlib.sha256(encoded).hexdigest()

    @api.constrains("effective_from", "effective_to")
    def _check_effective_period(self):
        for policy in self:
            if (
                policy.effective_from
                and policy.effective_to
                and policy.effective_to <= policy.effective_from
            ):
                raise ValidationError(
                    _("Policy end time must be later than its start time.")
                )

    def write(self, values):
        immutable_when_approved = {
            "campaign_id",
            "policy_type",
            "version",
            "settings_json",
            "effective_from",
            "effective_to",
        }
        if immutable_when_approved & values.keys() and any(
            policy.state == "approved" for policy in self
        ):
            raise AccessError(
                _("Approved campaign-policy versions are immutable; create a new version.")
            )
        if values.get("state") == "approved" and not (
            self.env.context.get("cc_security_approval")
            and self.env.user.has_group("base.group_system")
        ):
            raise AccessError(
                _("Policy approval is reserved for the security and approval module.")
            )
        return super().write(values)


class CallCenterBusinessUnitCanonicalAdoption(models.Model):
    _inherit = "call.center.business.unit"

    @api.model_create_multi
    def create(self, values_list):
        records = super().create(values_list)
        if not self.env.context.get("cc_skip_auto_adoption"):
            self.env["cc.business.unit"]._adopt_legacy_records()
        return records


class CallCenterCampaignCanonicalAdoption(models.Model):
    _inherit = "call.center.campaign"

    @api.model_create_multi
    def create(self, values_list):
        records = super().create(values_list)
        if not self.env.context.get("cc_skip_auto_adoption"):
            self.env["cc.business.unit"]._adopt_legacy_records()
        return records


class CallCenterCampaignMappingCanonicalAdoption(models.Model):
    _inherit = "call.center.campaign.mapping"

    @api.model_create_multi
    def create(self, values_list):
        records = super().create(values_list)
        if not self.env.context.get("cc_skip_auto_adoption"):
            self.env["cc.business.unit"]._adopt_legacy_records()
        return records
