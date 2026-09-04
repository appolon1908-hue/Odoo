import hashlib
import re

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .automatic_provisioning_common import (
    DESIGN_MANIFEST_SCHEMA,
    DESIGN_REVISION_STATES,
    ENVIRONMENT_SCOPE_CODES,
    LIST_ID_RANGES,
    REQUIRED_MANIFEST_POLICY_KEYS,
    REVISION_STATE_CAPABILITY,
    canonical_json,
    contains_secret_key,
    normalized_hash,
)

class CallCenterCampaignDesignRevision(models.Model):
    _name = "call.center.campaign.design.revision"
    _description = "Immutable Campaign Design Revision"
    _order = "campaign_id, revision desc"

    campaign_id = fields.Many2one(
        "call.center.campaign",
        required=True,
        ondelete="restrict",
        index=True,
        readonly=True,
    )
    business_unit_id = fields.Many2one(
        "call.center.business.unit",
        related="campaign_id.business_unit_id",
        store=True,
        readonly=True,
        index=True,
    )
    integration_uuid = fields.Char(required=True, readonly=True, index=True)
    revision = fields.Integer(required=True, readonly=True, index=True)
    event_uuid = fields.Char(required=True, readonly=True, index=True)
    environment = fields.Selection(
        [("test", "Test"), ("staging", "Staging"), ("production", "Production")],
        required=True,
        readonly=True,
        index=True,
    )
    state = fields.Selection(
        DESIGN_REVISION_STATES,
        required=True,
        default="requested",
        readonly=True,
        index=True,
    )
    request_payload_hash = fields.Char(required=True, size=64, readonly=True)
    validation_errors_json = fields.Json(readonly=True)
    manifest_schema_version = fields.Char(readonly=True)
    manifest_hash = fields.Char(size=64, readonly=True, index=True)
    manifest_json = fields.Json(readonly=True)
    requested_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True, index=True
    )
    received_at = fields.Datetime(readonly=True)
    approved_by = fields.Many2one("res.users", readonly=True)
    approved_at = fields.Datetime(readonly=True)
    approval_reason = fields.Char(readonly=True)

    _integration_revision_unique = models.Constraint(
        "unique(integration_uuid, revision)",
        "Campaign design revisions must be unique per integration identity.",
    )
    _event_uuid_unique = models.Constraint(
        "unique(event_uuid)", "Campaign design event UUIDs must be unique."
    )
    _revision_positive = models.Constraint(
        "check(revision > 0)", "Campaign design revisions must be positive."
    )
    _request_hash_format = models.Constraint(
        "check(length(request_payload_hash) = 64)",
        "Campaign design request hashes must be SHA-256 values.",
    )
    _manifest_hash_format = models.Constraint(
        "check(manifest_hash IS NULL OR length(manifest_hash) = 64)",
        "Campaign design manifest hashes must be SHA-256 values.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        if (
            self.env.context.get("_codestra_revision_capability")
            is not REVISION_STATE_CAPABILITY
        ):
            raise AccessError("Campaign design revisions are system controlled.")
        return super().create(vals_list)

    def write(self, vals):
        if (
            self.env.context.get("_codestra_revision_capability")
            is not REVISION_STATE_CAPABILITY
        ):
            raise AccessError("Campaign design revisions are system controlled.")
        return super().write(vals)

    def unlink(self):
        raise AccessError("Campaign design revisions are immutable.")

    @api.model
    def _create_internal(self, vals):
        return self.sudo().with_context(
            _codestra_revision_capability=REVISION_STATE_CAPABILITY
        ).create(vals)

    def _system_write(self, vals):
        return self.sudo().with_context(
            _codestra_revision_capability=REVISION_STATE_CAPABILITY
        ).write(vals)

    def _validate_manifest(self, manifest):
        self.ensure_one()
        if not isinstance(manifest, dict):
            raise ValidationError("Campaign design manifest must be a JSON object.")
        if contains_secret_key(manifest):
            raise ValidationError("Campaign design manifest contains a secret-shaped key.")
        campaign = self.campaign_id
        if manifest.get("schema_version") != DESIGN_MANIFEST_SCHEMA:
            raise ValidationError("Campaign design manifest schema is unsupported.")
        if str(manifest.get("environment", "")).lower() != self.environment:
            raise ValidationError("Campaign design manifest environment mismatch.")
        if manifest.get("integration_uuid") != self.integration_uuid:
            raise ValidationError("Campaign design manifest integration identity mismatch.")
        if manifest.get("design_revision") != self.revision:
            raise ValidationError("Campaign design manifest revision mismatch.")
        unit_code = campaign._business_unit_code()
        if str(manifest.get("business_unit", "")).upper() != unit_code:
            raise ValidationError("Campaign design manifest business-unit mismatch.")
        odoo_state = manifest.get("odoo")
        if not isinstance(odoo_state, dict):
            raise ValidationError("Campaign design manifest lacks Odoo state.")
        if (
            odoo_state.get("campaign_id") != campaign.id
            or odoo_state.get("campaign_code") != campaign.code
            or odoo_state.get("owner_user_id") != campaign.create_uid.id
            or odoo_state.get("supervisor_user_id") not in campaign.supervisor_ids.ids
        ):
            raise ValidationError("Campaign design manifest Odoo binding mismatch.")

        policies = manifest.get("policies")
        if not isinstance(policies, dict) or any(
            policies.get(key) in (None, "", [], {})
            for key in REQUIRED_MANIFEST_POLICY_KEYS
        ):
            raise ValidationError("Campaign design manifest policy envelope is incomplete.")
        if policies.get("time_zone") != campaign.timezone:
            raise ValidationError("Campaign design manifest time-zone policy mismatch.")

        vicidial = manifest.get("vicidial")
        if not isinstance(vicidial, dict) or vicidial.get("active") is not False:
            raise ValidationError("VICIdial preview resources must remain disabled.")
        if vicidial.get("campaign_id") != campaign.code:
            raise ValidationError("VICIdial campaign identity does not match Odoo.")
        list_range = LIST_ID_RANGES.get(unit_code)
        default_list_id = vicidial.get("default_list_id")
        if (
            not list_range
            or isinstance(default_list_id, bool)
            or not isinstance(default_list_id, int)
            or not list_range[0] <= default_list_id <= list_range[1]
        ):
            raise ValidationError("VICIdial default list ID is outside its business-unit range.")
        lists = vicidial.get("lists")
        if not isinstance(lists, list):
            raise ValidationError("VICIdial list design must be a JSON list.")
        for item in lists:
            list_id = item.get("list_id") if isinstance(item, dict) else None
            if (
                not isinstance(item, dict)
                or item.get("active") is not False
                or isinstance(list_id, bool)
                or not isinstance(list_id, int)
                or not list_range[0] <= list_id <= list_range[1]
            ):
                raise ValidationError(
                    "Every VICIdial list must be disabled and use its business-unit range."
                )
        resource_prefix = f"{unit_code}_{campaign.purpose_code}_"
        for field_name in ("user_groups", "inbound_groups", "scripts"):
            resources = vicidial.get(field_name)
            if not isinstance(resources, list) or any(
                not isinstance(value, str) or not value.startswith(resource_prefix)
                for value in resources
            ):
                raise ValidationError(
                    f"VICIdial {field_name} must use canonical campaign-owned identifiers."
                )
        disposition_set = vicidial.get("disposition_set")
        if not isinstance(disposition_set, str) or not disposition_set.startswith(
            resource_prefix
        ):
            raise ValidationError(
                "VICIdial disposition set must use the canonical campaign prefix."
            )

        n8n = manifest.get("n8n")
        if not isinstance(n8n, dict) or n8n.get("workflows_active") is not False:
            raise ValidationError("n8n preview workflows must remain inactive.")
        expected_scope = (
            f"{ENVIRONMENT_SCOPE_CODES[self.environment]}-{unit_code}-"
            f"{campaign.purpose_code}-V{self.revision}"
        )
        if n8n.get("scope") != expected_scope:
            raise ValidationError("n8n preview scope is not canonical for this revision.")
        feature_flags = manifest.get("feature_flags")
        required_flags = {
            "lead_publication",
            "agent_sync",
            "live_call_control",
            "production_dialing",
        }
        if not isinstance(feature_flags, dict) or any(
            feature_flags.get(flag) is not False for flag in required_flags
        ):
            raise ValidationError("Campaign design preview must keep all live flags false.")
        return True

    def _record_preview(self, result):
        self.ensure_one()
        result_revision = result.get("design_revision")
        if isinstance(result_revision, bool) or result_revision != self.revision:
            raise ValidationError("Middleware design revision does not match the request.")
        manifest_hash = normalized_hash(result.get("manifest_hash"))
        if re.fullmatch(r"[0-9a-f]{64}", manifest_hash) is None:
            raise ValidationError("Middleware design manifest hash is invalid.")
        manifest = result.get("manifest") or result.get("design_manifest")
        validation_errors = result.get(
            "validation_errors", self.validation_errors_json or []
        )
        if not isinstance(validation_errors, list):
            raise ValidationError("Middleware validation errors must be a JSON list.")
        local_errors = self.campaign_id._design_validation_errors()
        combined_errors = list(
            dict.fromkeys([str(error) for error in [*local_errors, *validation_errors]])
        )
        values = {
            "manifest_hash": manifest_hash,
            "received_at": fields.Datetime.now(),
            "validation_errors_json": combined_errors,
        }
        if manifest is None:
            values["state"] = "hash_only"
            return self._system_write(values)
        self._validate_manifest(manifest)
        calculated_hash = hashlib.sha256(canonical_json(manifest).encode()).hexdigest()
        if calculated_hash != manifest_hash:
            raise ValidationError("Campaign design manifest hash does not match its JSON.")
        values.update(
            {
                "manifest_schema_version": manifest["schema_version"],
                "manifest_json": manifest,
                "state": "rejected" if combined_errors else "ready",
            }
        )
        return self._system_write(values)
