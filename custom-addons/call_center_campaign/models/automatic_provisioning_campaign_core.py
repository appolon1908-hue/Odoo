import re

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .automatic_provisioning_common import (
    APPROVED_BUSINESS_UNITS,
    AUTOMATIC_STATE_CAPABILITY,
    DESIGN_REVISION_STATES,
    DIRECTION_CODES,
    REQUIRED_DESIGN_INPUT_KEYS,
    contains_secret_key,
)

class CallCenterCampaignAutomaticProvisioning(models.Model):
    _inherit = "call.center.campaign"

    provisioning_environment = fields.Selection(
        [("test", "Test"), ("staging", "Staging"), ("production", "Production")],
        default="staging",
        required=True,
        tracking=True,
    )
    design_input_json = fields.Json(
        default=dict,
        help=(
            "Reviewed campaign-design inputs. Required keys are documented in "
            "AUTOMATIC_CAMPAIGN_PROVISIONING.md."
        ),
    )
    automatic_design_managed = fields.Boolean(
        default=False, readonly=True, copy=False, index=True
    )
    design_revision_ids = fields.One2many(
        "call.center.campaign.design.revision", "campaign_id", readonly=True
    )
    current_design_revision_id = fields.Many2one(
        "call.center.campaign.design.revision",
        compute="_compute_current_design_revision",
        readonly=True,
    )
    automatic_design_state = fields.Selection(
        DESIGN_REVISION_STATES,
        compute="_compute_current_design_revision",
        readonly=True,
    )
    design_manifest_hash = fields.Char(
        compute="_compute_current_design_revision", readonly=True
    )
    design_preview_received_at = fields.Datetime(
        compute="_compute_current_design_revision", readonly=True
    )
    design_validation_errors_json = fields.Json(
        compute="_compute_current_design_revision", readonly=True
    )
    design_approval_reason = fields.Char(copy=False, tracking=True)
    last_approval_event_uuid = fields.Char(readonly=True, copy=False, index=True)

    @api.depends(
        "design_request_revision",
        "design_revision_ids.revision",
        "design_revision_ids.state",
        "design_revision_ids.manifest_hash",
        "design_revision_ids.received_at",
        "design_revision_ids.validation_errors_json",
    )
    def _compute_current_design_revision(self):
        for campaign in self:
            current = campaign.design_revision_ids.filtered(
                lambda revision: revision.revision == campaign.design_request_revision
            )[:1]
            campaign.current_design_revision_id = current
            campaign.automatic_design_state = current.state if current else False
            campaign.design_manifest_hash = current.manifest_hash if current else False
            campaign.design_preview_received_at = current.received_at if current else False
            campaign.design_validation_errors_json = (
                current.validation_errors_json if current else []
            )

    @api.model
    def _automatic_design_default_allowed(self):
        context = self.env.context
        return not any(
            context.get(flag)
            for flag in (
                "install_mode",
                "import_file",
                "module",
                "codestra_skip_automatic_campaign_design",
            )
        )

    @api.model
    def _normalize_purpose_code(self, value):
        return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())[:16]

    @api.model
    def _derive_purpose_code(self, values):
        explicit = self._normalize_purpose_code(values.get("purpose_code"))
        if explicit:
            return explicit
        code = str(values.get("code") or "").upper()
        tokens = [token for token in re.split(r"[^A-Z0-9]+", code) if token]
        business_unit_id = values.get("business_unit_id")
        unit = self.env["call.center.business.unit"].browse(business_unit_id).exists()
        unit_code = str(unit.code or "").upper() if unit else ""
        if tokens and unit_code and tokens[0] == unit_code:
            tokens.pop(0)
        if tokens and tokens[-1] in {"IN", "OUT", "BLENDED"}:
            tokens.pop()
        derived = self._normalize_purpose_code("".join(tokens))
        return derived or "UNSPECIFIED"

    @api.model_create_multi
    def create(self, vals_list):
        created_ids = []
        allow_default = self._automatic_design_default_allowed()
        for original in vals_list:
            values = dict(original)
            explicitly_disabled = values.get("design_automation_enabled") is False
            if (
                explicitly_disabled
                and allow_default
                and not self.env.user.has_group(
                    "call_center_core.group_call_center_admin"
                )
            ):
                raise AccessError(
                    "Only a call-center administrator may create an unmanaged "
                    "campaign for a reviewed migration."
                )
            automatic_default = allow_default and (
                "design_automation_enabled" not in values
                or (
                    self.env.context.get("codestra_automatic_campaign_form")
                    and values.get("design_automation_enabled") is True
                )
            )
            if "automatic_design_managed" in values and not self.env.context.get(
                "codestra_skip_automatic_campaign_design"
            ):
                raise AccessError("Automatic campaign-design ownership is system controlled.")
            if automatic_default:
                if values.get("state") in {"approved", "active"}:
                    raise ValidationError(
                        "A new campaign must begin in draft before design approval."
                    )
                values["design_automation_enabled"] = True
                values["automatic_design_managed"] = True
                values.setdefault("purpose_code", self._derive_purpose_code(values))
                values.setdefault("provisioning_environment", "staging")
                values.setdefault("design_input_json", {})
            record = super(
                CallCenterCampaignAutomaticProvisioning,
                self.with_context(_codestra_automatic_default=automatic_default),
            ).create([values])
            created_ids.extend(record.ids)
        return self.browse(created_ids)

    def write(self, vals):
        if (
            self.env.context.get("_codestra_automatic_state_capability")
            is AUTOMATIC_STATE_CAPABILITY
        ):
            return super().write(vals)
        system_fields = {"automatic_design_managed", "last_approval_event_uuid"}
        if system_fields & vals.keys() and not self.env.context.get(
            "codestra_skip_automatic_campaign_design"
        ):
            raise AccessError("Automatic campaign-design state is system controlled.")
        if (
            vals.get("design_automation_enabled") is False
            and any(self.mapped("automatic_design_managed"))
            and not self.env.context.get("codestra_skip_automatic_campaign_design")
        ):
            raise AccessError(
                "Automatically managed campaign design cannot be disabled outside migration."
            )
        native_design_fields = {
            "business_unit_id",
            "purpose_code",
            "direction",
            "timezone",
            "calling_hour_start",
            "calling_hour_end",
            "consent_required",
            "dnc_enforced",
            "team_ids",
            "supervisor_ids",
        }
        extra_design_fields = {
            "name",
            "code",
            "campaign_type",
            "lead_source_id",
            "dialer_mode",
            "routing_strategy",
            "max_call_attempts",
            "max_retries",
            "callback_rule",
            "escalation_rule",
            "provisioning_environment",
            "design_input_json",
        }
        approving = vals.get("state") == "approved"
        changing_design = bool((native_design_fields | extra_design_fields) & vals.keys())
        if approving and changing_design:
            raise ValidationError(
                "Save campaign design changes before approving the design revision."
            )
        campaigns_to_approve = self.filtered(
            lambda campaign: approving
            and (campaign.state != "approved" or campaign.automatic_design_state != "approved")
        )
        for campaign in campaigns_to_approve:
            campaign._validate_design_approval()
        result = super().write(vals)
        if extra_design_fields & vals.keys() and not native_design_fields & vals.keys():
            for campaign in self.filtered("design_automation_enabled"):
                campaign._create_design_request_event()
        for campaign in campaigns_to_approve:
            campaign._finalize_design_approval()
        return result

    def _system_write(self, vals):
        return self.with_context(
            _codestra_automatic_state_capability=AUTOMATIC_STATE_CAPABILITY
        ).write(vals)

    def _business_unit_code(self):
        self.ensure_one()
        return str(self.business_unit_id.code or "").upper() or "UNASSIGNED"

    def _canonical_campaign_code(self):
        self.ensure_one()
        direction = DIRECTION_CODES.get(self.direction, str(self.direction or "").upper())
        purpose = self.purpose_code or "UNSPECIFIED"
        return f"{self._business_unit_code()}-{purpose}-{direction}".upper()

    def _design_validation_errors(self):
        self.ensure_one()
        errors = []
        unit_code = self._business_unit_code()
        if unit_code not in APPROVED_BUSINESS_UNITS:
            errors.append("BUSINESS_UNIT_NOT_APPROVED")
        if not self.purpose_code:
            errors.append("PURPOSE_REQUIRED")
        elif self._normalize_purpose_code(self.purpose_code) != self.purpose_code:
            errors.append("PURPOSE_CODE_NOT_CANONICAL")
        if self.code != self._canonical_campaign_code():
            errors.append(f"CAMPAIGN_CODE_MUST_EQUAL:{self._canonical_campaign_code()}")
        if not self.timezone:
            errors.append("TIME_ZONE_REQUIRED")
        if not self.supervisor_ids:
            errors.append("SUPERVISOR_REQUIRED")
        design_input = self.design_input_json or {}
        if not isinstance(design_input, dict):
            errors.append("DESIGN_INPUT_MUST_BE_OBJECT")
            design_input = {}
        for key in sorted(REQUIRED_DESIGN_INPUT_KEYS):
            if design_input.get(key) in (None, "", [], {}):
                errors.append(f"DESIGN_INPUT_REQUIRED:{key}")
        if contains_secret_key(design_input):
            errors.append("DESIGN_INPUT_CONTAINS_SECRET_SHAPED_KEY")
        return errors

    def _design_request_payload(self, event_uuid, correlation_id):
        self.ensure_one()
        validation_errors = self._design_validation_errors()
        design_input = self.design_input_json or {}
        return {
            "schema_version": DESIGN_MANIFEST_SCHEMA,
            "event_id": event_uuid,
            "integration_uuid": self.integration_uuid,
            "odoo_campaign_id": self.id,
            "environment": self.provisioning_environment,
            "business_unit": self._business_unit_code(),
            "purpose": self.purpose_code,
            "direction": self.direction,
            "campaign_code": self.code,
            "expected_campaign_code": self._canonical_campaign_code(),
            "owner_user_id": self.create_uid.id,
            "supervisor_user_id": self.supervisor_ids[:1].id or None,
            "correlation_id": correlation_id,
            "validation": {
                "status": "BLOCKED" if validation_errors else "READY",
                "errors": validation_errors,
            },
            "design_configuration": {
                "time_zone": self.timezone,
                "calling_hour_start": self.calling_hour_start,
                "calling_hour_end": self.calling_hour_end,
                "consent_required": self.consent_required,
                "dnc_enforced": self.dnc_enforced,
                "campaign_type": self.campaign_type,
                "lead_source_id": self.lead_source_id.id or None,
                "dialer_mode": self.dialer_mode,
                "routing_strategy": self.routing_strategy,
                "max_call_attempts": self.max_call_attempts,
                "max_retries": self.max_retries,
                "callback_rule": self.callback_rule,
                "escalation_rule": self.escalation_rule,
                "team_ids": sorted(self.team_ids.ids),
                "supervisor_ids": sorted(self.supervisor_ids.ids),
                "inputs": design_input,
            },
            "feature_flags": {
                "lead_publication": False,
                "agent_sync": False,
                "live_call_control": False,
                "production_dialing": False,
            },
        }
