import hashlib
import json
import re

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


SCRIPT_CONTENT_FIELDS = (
    "opening",
    "identity_verification",
    "ai_disclosure",
    "recording_disclosure",
    "qualification_questions",
    "product_explanation",
    "objection_handling",
    "pricing_guidance",
    "closing",
    "required_legal_statements",
    "opt_out_language",
    "escalation_instructions",
    "prohibited_statements",
    "supervisor_notes",
)
AGENT_RENDER_FIELDS = tuple(
    field_name
    for field_name in SCRIPT_CONTENT_FIELDS
    if field_name not in {"prohibited_statements", "supervisor_notes"}
)
REQUIRED_SCRIPT_FIELDS = {
    "opening",
    "identity_verification",
    "recording_disclosure",
    "closing",
    "required_legal_statements",
    "opt_out_language",
}
SCRIPT_IDENTITY_FIELDS = {
    "campaign_id",
    "business_unit_id",
    "language_code",
    "version",
}
DISPOSITION_SOURCE_FIELDS = {
    "code",
    "name",
    "category",
    "campaign_id",
    "business_unit_id",
    "vicidial_status_code",
    "canonical_status_id",
    "human_contact",
    "attempt",
    "note_required",
    "callback_required",
    "retry_interval_minutes",
    "maximum_retries",
    "stage_change_policy",
    "allowed_next_stage_ids",
    "compliance_block",
    "terminal",
    "agent_visible",
    "supervisor_approval_required",
    "active",
}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
EVENT_NAME_PATTERN = re.compile(r"^cc\.[a-z0-9_.-]+\.v[1-9][0-9]*$")
SCRIPT_VERSION_CAPABILITY = object()
SCRIPT_ACK_CAPABILITY = object()
DISPOSITION_CATALOG_CAPABILITY = object()


def _require_configuration_user(user):
    if not (
        user.has_group("codestra_cc_security.group_cc_campaign_configuration_manager")
        or user.has_group("codestra_cc_security.group_cc_global_administrator")
    ):
        raise AccessError(
            _("Campaign configuration authority is required for this operation.")
        )


def _is_operational_user(user):
    return any(
        user.has_group(xmlid)
        for xmlid in (
            "codestra_cc_security.group_cc_campaign_agent",
            "codestra_cc_security.group_cc_senior_agent",
            "codestra_cc_security.group_cc_campaign_supervisor",
        )
    )


def _canonical_json_hash(payload):
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class CcScript(models.Model):
    _name = "cc.script"
    _description = "Campaign-Owned Call Script"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "campaign_id, name, language_code"

    name = fields.Char(required=True, index=True)
    language_code = fields.Char(required=True, default="en", index=True)
    active = fields.Boolean(default=True, required=True, index=True)
    version_ids = fields.One2many("cc.script.version", "script_id", readonly=True)
    active_version_id = fields.Many2one(
        "cc.script.version", compute="_compute_active_version", readonly=True
    )

    _campaign_name_language_unique = models.Constraint(
        "unique(campaign_id, name, language_code)",
        "Script identities must be unique by campaign, name, and language.",
    )

    @api.depends("version_ids.governance_state")
    def _compute_active_version(self):
        Version = self.env["cc.script.version"]
        for script in self:
            script.active_version_id = Version.search(
                [
                    ("script_id", "=", script.id),
                    ("governance_state", "=", "approved"),
                ],
                order="version_number desc, id desc",
                limit=1,
            )

    @api.model_create_multi
    def create(self, values_list):
        _require_configuration_user(self.env.user)
        for values in values_list:
            campaign = self.env["cc.campaign"].browse(
                values.get("campaign_id")
            ).exists()
            if not campaign:
                raise ValidationError(_("A canonical campaign is required."))
            campaign.check_access("read")
        return super().create(values_list)

    def write(self, values):
        _require_configuration_user(self.env.user)
        if {"campaign_id", "name", "language_code"}.intersection(values) and any(
            script.version_ids for script in self
        ):
            raise AccessError(
                _("Script identity is immutable after its first version is created.")
            )
        return super().write(values)

    def unlink(self):
        raise AccessError(_("Campaign scripts are retired, not deleted."))

    def copy(self, default=None):
        raise AccessError(_("Create an explicit campaign-owned script instead of copying."))

    def export_data(self, fields_to_export, raw_data=False):
        if _is_operational_user(self.env.user):
            raise UserError(_("Agent and supervisor script export is disabled."))
        return super().export_data(fields_to_export, raw_data=raw_data)

    def action_create_version(self, content=None):
        self.ensure_one()
        _require_configuration_user(self.env.user)
        self.check_access("read")
        content = dict(content or {})
        unknown = set(content) - set(SCRIPT_CONTENT_FIELDS)
        if unknown:
            raise ValidationError(
                _("Unknown script sections: %(fields)s", fields=", ".join(sorted(unknown)))
            )
        next_number = max(self.version_ids.mapped("version_number"), default=0) + 1
        values = {
            "script_id": self.id,
            "version_number": next_number,
            "name": f"{self.name} v{next_number}",
            "campaign_id": self.campaign_id.legacy_campaign_id.id,
            "business_unit_id": (
                self.campaign_id.cc_business_unit_id.legacy_business_unit_id.id
            ),
            "language_code": self.language_code,
            "version": str(next_number),
            "state": "draft",
            **content,
        }
        created = self.env["cc.script.version"].with_context(
            _cc_script_version_capability=SCRIPT_VERSION_CAPABILITY
        ).create(values)
        return self.env["cc.script.version"].browse(created.ids)

    def action_adopt_legacy_version(self, legacy_script_id):
        self.ensure_one()
        _require_configuration_user(self.env.user)
        legacy = self.env["call.center.script"].browse(legacy_script_id).exists()
        if not legacy:
            raise ValidationError(_("The legacy script version does not exist."))
        legacy.check_access("read")
        if legacy.campaign_id != self.campaign_id.legacy_campaign_id:
            raise ValidationError(_("Legacy and canonical scripts must share a campaign."))
        if legacy.language_code != self.language_code:
            raise ValidationError(_("Legacy and canonical scripts must share a language."))
        if self.env["cc.script.version"].search_count(
            [("legacy_script_id", "=", legacy.id)], limit=1
        ):
            raise ValidationError(_("The legacy script version is already adopted."))
        next_number = max(self.version_ids.mapped("version_number"), default=0) + 1
        created = self.env["cc.script.version"].with_context(
            _cc_script_version_capability=SCRIPT_VERSION_CAPABILITY
        ).create(
            {
                "script_id": self.id,
                "version_number": next_number,
                "legacy_script_id": legacy.id,
                "governance_state": "draft",
            }
        )
        return self.env["cc.script.version"].browse(created.ids)

    def action_render_active(self):
        self.ensure_one()
        membership = self.env.user._cc_resolve_operational_membership()
        if membership.campaign_id != self.campaign_id:
            raise AccessError(_("The active campaign membership determines script scope."))
        version = self.active_version_id
        if not version:
            raise UserError(_("No approved script version is available for this campaign."))
        return version._render_for_membership(membership)


class CcScriptVersion(models.Model):
    _name = "cc.script.version"
    _description = "Immutable Campaign Call Script Version"
    _inherits = {"call.center.script": "legacy_script_id"}
    _order = "script_id, version_number desc"

    legacy_script_id = fields.Many2one(
        "call.center.script", required=True, ondelete="restrict", index=True, copy=False
    )
    script_id = fields.Many2one(
        "cc.script", required=True, ondelete="restrict", index=True, copy=False
    )
    cc_campaign_id = fields.Many2one(
        "cc.campaign",
        string="Canonical Campaign Workspace",
        related="script_id.campaign_id",
        store=True,
        readonly=True,
        index=True,
    )
    version_number = fields.Integer(required=True, readonly=True, copy=False)
    governance_state = fields.Selection(
        [
            ("draft", "Draft"),
            ("review", "In Review"),
            ("approved", "Approved"),
            ("retired", "Retired"),
        ],
        required=True,
        default="draft",
        readonly=True,
        index=True,
        copy=False,
    )
    content_hash = fields.Char(
        compute="_compute_content_hash", store=True, readonly=True, index=True
    )
    submitted_by_id = fields.Many2one(
        "res.users", readonly=True, ondelete="restrict", copy=False
    )
    submitted_at = fields.Datetime(readonly=True, copy=False)
    approved_by_id = fields.Many2one(
        "res.users", readonly=True, ondelete="restrict", copy=False
    )
    approved_at = fields.Datetime(readonly=True, copy=False)
    approval_ticket = fields.Char(readonly=True, copy=False, index=True)
    approval_ticket_input = fields.Char(copy=False)
    required_acknowledgement = fields.Boolean(default=True, required=True)
    acknowledgement_ids = fields.One2many(
        "cc.script.acknowledgement", "version_id", readonly=True
    )

    _legacy_script_unique = models.Constraint(
        "unique(legacy_script_id)", "A legacy script version may be adopted only once."
    )
    _script_version_unique = models.Constraint(
        "unique(script_id, version_number)",
        "Script version numbers must be unique inside a script.",
    )
    _positive_version = models.Constraint(
        "check(version_number > 0)", "Script version numbers must be positive."
    )
    _one_approved_version = models.UniqueIndex(
        "(script_id) WHERE governance_state = 'approved'",
        "A script may have only one approved active version.",
    )

    @api.depends("script_id", "version_number", *SCRIPT_CONTENT_FIELDS)
    def _compute_content_hash(self):
        for version in self:
            version.content_hash = _canonical_json_hash(
                {
                    "campaign_uuid": version.cc_campaign_id.workspace_uuid,
                    "script": version.script_id.name,
                    "language": version.language_code,
                    "version": version.version_number,
                    "content": {
                        field_name: str(version[field_name] or "")
                        for field_name in SCRIPT_CONTENT_FIELDS
                    },
                }
            )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get(
            "_cc_script_version_capability"
        ) is not SCRIPT_VERSION_CAPABILITY:
            raise AccessError(_("Script versions require the governed creation workflow."))
        records = super().create(values_list)
        records._check_canonical_identity()
        return records

    def write(self, values):
        _require_configuration_user(self.env.user)
        capability = self.env.context.get("_cc_script_version_capability")
        if {"legacy_script_id", "script_id", "version_number"}.intersection(values):
            raise AccessError(_("Script version ownership and identity are immutable."))
        if {"governance_state", "submitted_by_id", "submitted_at", "approved_by_id", "approved_at", "approval_ticket"}.intersection(values) and capability is not SCRIPT_VERSION_CAPABILITY:
            raise AccessError(_("Script governance transitions require the approved workflow."))
        if set(values).intersection(set(SCRIPT_CONTENT_FIELDS) | SCRIPT_IDENTITY_FIELDS) and any(
            version.governance_state != "draft" for version in self
        ):
            raise AccessError(_("Reviewed script versions are immutable."))
        result = super().write(values)
        self._check_canonical_identity()
        return result

    def unlink(self):
        raise AccessError(_("Script versions are immutable evidence and cannot be deleted."))

    def copy(self, default=None):
        raise AccessError(_("Create the next explicit script version instead of copying."))

    def export_data(self, fields_to_export, raw_data=False):
        if _is_operational_user(self.env.user):
            raise UserError(_("Agent and supervisor script export is disabled."))
        return super().export_data(fields_to_export, raw_data=raw_data)

    @api.constrains("legacy_script_id", "script_id", "version_number")
    def _check_canonical_identity(self):
        for version in self:
            if version.legacy_script_id.campaign_id != version.cc_campaign_id.legacy_campaign_id:
                raise ValidationError(_("Canonical and legacy script campaigns must match."))
            if version.language_code != version.script_id.language_code:
                raise ValidationError(_("Script version language must match its script."))
            if str(version.version or "") != str(version.version_number):
                raise ValidationError(_("Legacy and canonical version numbers must match."))

    def _transition(self, governance_state, extra_values=None):
        values = dict(extra_values or {}, governance_state=governance_state)
        legacy_state = {
            "draft": "draft",
            "review": "review",
            "approved": "approved",
            "retired": "retired",
        }[governance_state]
        values["state"] = legacy_state
        return self.with_context(
            _cc_script_version_capability=SCRIPT_VERSION_CAPABILITY
        ).write(values)

    def action_submit_for_review(self):
        self.ensure_one()
        _require_configuration_user(self.env.user)
        if self.governance_state != "draft":
            raise ValidationError(_("Only draft script versions can enter review."))
        missing = [
            field_name
            for field_name in sorted(REQUIRED_SCRIPT_FIELDS)
            if not str(self[field_name] or "").strip()
        ]
        if missing:
            raise ValidationError(
                _("Required script sections are missing: %(fields)s", fields=", ".join(missing))
            )
        return self._transition(
            "review",
            {
                "submitted_by_id": self.env.user.id,
                "submitted_at": fields.Datetime.now(),
            },
        )

    def action_approve(self, approval_ticket=None):
        self.ensure_one()
        _require_configuration_user(self.env.user)
        if self.governance_state != "review":
            raise ValidationError(_("Only reviewed script versions can be approved."))
        if self.env.user.id in {self.create_uid.id, self.submitted_by_id.id}:
            raise AccessError(_("The script author or submitter cannot approve it."))
        approval_ticket = approval_ticket or self.approval_ticket_input
        if not str(approval_ticket or "").strip():
            raise ValidationError(_("Script approval requires a ticket reference."))
        if self.search_count(
            [
                ("script_id", "=", self.script_id.id),
                ("governance_state", "=", "approved"),
                ("id", "!=", self.id),
            ],
            limit=1,
        ):
            raise ValidationError(_("Retire the current approved version first."))
        return self._transition(
            "approved",
            {
                "approved_by_id": self.env.user.id,
                "approved_at": fields.Datetime.now(),
                "approval_ticket": str(approval_ticket).strip(),
                "approval_ticket_input": False,
            },
        )

    def action_retire(self):
        self.ensure_one()
        _require_configuration_user(self.env.user)
        if self.governance_state != "approved":
            raise ValidationError(_("Only an approved script version can be retired."))
        return self._transition("retired")

    def _render_for_membership(self, membership):
        self.ensure_one()
        if self.governance_state != "approved":
            raise AccessError(_("Only the approved script version may be rendered."))
        if membership.campaign_id != self.cc_campaign_id:
            raise AccessError(_("The script belongs to another campaign."))
        if self.script_id.active_version_id != self:
            raise AccessError(_("Only the current approved script version may be rendered."))
        return {
            "script_id": self.script_id.id,
            "version_id": self.id,
            "campaign_code": self.cc_campaign_id.code,
            "language_code": self.language_code,
            "version": self.version_number,
            "content_hash": self.content_hash,
            "required_acknowledgement": self.required_acknowledgement,
            "sections": {
                field_name: str(self[field_name] or "")
                for field_name in AGENT_RENDER_FIELDS
            },
        }

    def action_acknowledge(self, event_id):
        self.ensure_one()
        membership = self.env.user._cc_resolve_operational_membership()
        self._render_for_membership(membership)
        event_id = str(event_id or "").strip()
        if not event_id:
            raise ValidationError(_("Acknowledgement event ID is required."))
        Acknowledgement = self.env["cc.script.acknowledgement"]
        existing = Acknowledgement.search([("event_id", "=", event_id)], limit=1)
        if existing:
            if existing.version_id != self or existing.user_id != self.env.user:
                raise ValidationError(_("Acknowledgement event ID was already used."))
            return existing
        prior = Acknowledgement.search(
            [("version_id", "=", self.id), ("user_id", "=", self.env.user.id)],
            limit=1,
        )
        if prior:
            raise ValidationError(_("This script version was acknowledged with another event."))
        created = Acknowledgement.with_context(
            _cc_script_ack_capability=SCRIPT_ACK_CAPABILITY
        ).create(
            {
                "version_id": self.id,
                "membership_id": membership.id,
                "user_id": self.env.user.id,
                "event_id": event_id,
                "content_hash": self.content_hash,
            }
        )
        return Acknowledgement.browse(created.ids)


class CcScriptAcknowledgement(models.Model):
    _name = "cc.script.acknowledgement"
    _description = "Immutable Script Acknowledgement"
    _order = "acknowledged_at desc, id desc"

    version_id = fields.Many2one(
        "cc.script.version", required=True, ondelete="restrict", index=True, copy=False
    )
    campaign_id = fields.Many2one(
        "cc.campaign",
        related="version_id.cc_campaign_id",
        store=True,
        readonly=True,
        index=True,
    )
    membership_id = fields.Many2one(
        "cc.campaign.membership", required=True, ondelete="restrict", index=True, copy=False
    )
    user_id = fields.Many2one(
        "res.users", required=True, ondelete="restrict", index=True, copy=False
    )
    event_id = fields.Char(required=True, readonly=True, index=True, copy=False)
    content_hash = fields.Char(required=True, size=64, readonly=True, copy=False)
    acknowledged_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True, copy=False
    )

    _version_user_unique = models.Constraint(
        "unique(version_id, user_id)",
        "A user may acknowledge a script version only once.",
    )
    _event_unique = models.Constraint(
        "unique(event_id)", "Script acknowledgement event IDs must be unique."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_script_ack_capability") is not SCRIPT_ACK_CAPABILITY:
            raise AccessError(_("Script acknowledgement requires the governed workflow."))
        records = super().create(values_list)
        for record in records:
            if record.membership_id.user_id != record.user_id:
                raise ValidationError(_("Acknowledgement membership and user must match."))
            if record.membership_id.campaign_id != record.campaign_id:
                raise ValidationError(_("Acknowledgement membership and script must share a campaign."))
            if record.content_hash != record.version_id.content_hash:
                raise ValidationError(_("Acknowledgement must bind the rendered content hash."))
        return records

    def write(self, values):
        raise AccessError(_("Script acknowledgements are append-only."))

    def unlink(self):
        raise AccessError(_("Script acknowledgements are append-only."))

    def copy(self, default=None):
        raise AccessError(_("Script acknowledgements cannot be copied."))

    def export_data(self, fields_to_export, raw_data=False):
        if _is_operational_user(self.env.user):
            raise UserError(_("Agent and supervisor acknowledgement export is disabled."))
        return super().export_data(fields_to_export, raw_data=raw_data)


class CcDispositionSet(models.Model):
    _name = "cc.disposition.set"
    _description = "Campaign-Owned Disposition Set Version"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "campaign_id, version desc"

    name = fields.Char(required=True)
    version = fields.Integer(required=True, default=1)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("review", "In Review"),
            ("approved", "Approved"),
            ("retired", "Retired"),
        ],
        required=True,
        default="draft",
        readonly=True,
        index=True,
        copy=False,
    )
    catalog_status = fields.Selection(
        [("missing", "Missing"), ("validated", "Validated"), ("rejected", "Rejected")],
        required=True,
        default="missing",
        readonly=True,
        index=True,
        copy=False,
    )
    catalog_sha256 = fields.Char(readonly=True, size=64, index=True, copy=False)
    catalog_row_count = fields.Integer(default=0, readonly=True, copy=False)
    catalog_evidence_reference = fields.Char(readonly=True, copy=False)
    submitted_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    submitted_at = fields.Datetime(readonly=True, copy=False)
    approved_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    approval_ticket = fields.Char(readonly=True, copy=False, index=True)
    approval_ticket_input = fields.Char(copy=False)
    disposition_ids = fields.One2many("cc.disposition", "set_id", readonly=True)

    _campaign_version_unique = models.Constraint(
        "unique(campaign_id, version)",
        "Disposition-set versions must be unique inside a campaign.",
    )
    _positive_version = models.Constraint(
        "check(version > 0)", "Disposition-set versions must be positive."
    )
    _one_approved_set = models.UniqueIndex(
        "(campaign_id) WHERE state = 'approved'",
        "A campaign may have only one approved disposition-set version.",
    )

    @api.model_create_multi
    def create(self, values_list):
        _require_configuration_user(self.env.user)
        for values in values_list:
            if values.get("state", "draft") != "draft" or values.get(
                "catalog_status", "missing"
            ) != "missing":
                raise AccessError(_("Disposition sets start as blocked drafts."))
            campaign = self.env["cc.campaign"].browse(values.get("campaign_id")).exists()
            if not campaign:
                raise ValidationError(_("A canonical campaign is required."))
            campaign.check_access("read")
        return super().create(values_list)

    def write(self, values):
        _require_configuration_user(self.env.user)
        capability = self.env.context.get("_cc_disposition_catalog_capability")
        protected = {
            "campaign_id",
            "version",
            "state",
            "catalog_status",
            "catalog_sha256",
            "catalog_row_count",
            "catalog_evidence_reference",
            "submitted_by_id",
            "submitted_at",
            "approved_by_id",
            "approved_at",
            "approval_ticket",
        }
        if protected.intersection(values) and capability is not DISPOSITION_CATALOG_CAPABILITY:
            raise AccessError(_("Disposition ownership, catalog evidence, and state are governed."))
        if (
            any(record.state != "draft" for record in self)
            and capability is not DISPOSITION_CATALOG_CAPABILITY
            and set(values) != {"approval_ticket_input"}
        ):
            raise AccessError(_("Reviewed disposition-set versions are immutable."))
        return super().write(values)

    def unlink(self):
        raise AccessError(_("Disposition-set versions are retained, not deleted."))

    def copy(self, default=None):
        raise AccessError(_("Create an explicit next disposition-set version."))

    def export_data(self, fields_to_export, raw_data=False):
        if _is_operational_user(self.env.user):
            raise UserError(_("Agent and supervisor disposition export is disabled."))
        return super().export_data(fields_to_export, raw_data=raw_data)

    def _record_catalog_validation(self, catalog_sha256, row_count, evidence_reference):
        if self.env.context.get(
            "_cc_disposition_catalog_capability"
        ) is not DISPOSITION_CATALOG_CAPABILITY:
            raise AccessError(_("Catalog evidence requires the controlled importer."))
        self.ensure_one()
        if not SHA256_PATTERN.fullmatch(str(catalog_sha256 or "").lower()):
            raise ValidationError(_("Catalog evidence requires a SHA-256 hash."))
        if row_count != 2677:
            raise ValidationError(_("The controlled catalog must contain exactly 2,677 rows."))
        if not str(evidence_reference or "").startswith("staging://"):
            raise ValidationError(_("Catalog evidence must use an approved staging reference."))
        return self.write(
            {
                "catalog_status": "validated",
                "catalog_sha256": str(catalog_sha256).lower(),
                "catalog_row_count": row_count,
                "catalog_evidence_reference": str(evidence_reference),
            }
        )

    def action_submit_for_review(self):
        self.ensure_one()
        _require_configuration_user(self.env.user)
        if self.state != "draft":
            raise ValidationError(_("Only draft disposition sets can enter review."))
        if (
            self.catalog_status != "validated"
            or self.catalog_row_count != 2677
            or not self.catalog_sha256
            or not self.catalog_evidence_reference
        ):
            raise UserError(
                _("The original validated 2,677-row disposition catalog is required.")
            )
        if not self.disposition_ids:
            raise UserError(_("A validated catalog cannot produce an empty disposition set."))
        return self.with_context(
            _cc_disposition_catalog_capability=DISPOSITION_CATALOG_CAPABILITY
        ).write(
            {
                "state": "review",
                "submitted_by_id": self.env.user.id,
                "submitted_at": fields.Datetime.now(),
            }
        )

    def action_approve(self, approval_ticket=None):
        self.ensure_one()
        _require_configuration_user(self.env.user)
        if self.state != "review":
            raise ValidationError(_("Only reviewed disposition sets can be approved."))
        if self.env.user.id in {self.create_uid.id, self.submitted_by_id.id}:
            raise AccessError(_("The disposition author or submitter cannot approve it."))
        approval_ticket = approval_ticket or self.approval_ticket_input
        if not str(approval_ticket or "").strip():
            raise ValidationError(_("Disposition approval requires a ticket reference."))
        if self.search_count(
            [
                ("campaign_id", "=", self.campaign_id.id),
                ("state", "=", "approved"),
                ("id", "!=", self.id),
            ],
            limit=1,
        ):
            raise ValidationError(_("Retire the current approved disposition set first."))
        return self.with_context(
            _cc_disposition_catalog_capability=DISPOSITION_CATALOG_CAPABILITY
        ).write(
            {
                "state": "approved",
                "approved_by_id": self.env.user.id,
                "approved_at": fields.Datetime.now(),
                "approval_ticket": str(approval_ticket).strip(),
                "approval_ticket_input": False,
            }
        )

    def action_retire(self):
        self.ensure_one()
        _require_configuration_user(self.env.user)
        if self.state != "approved":
            raise ValidationError(_("Only an approved disposition set can be retired."))
        return self.with_context(
            _cc_disposition_catalog_capability=DISPOSITION_CATALOG_CAPABILITY
        ).write({"state": "retired"})


class CcDisposition(models.Model):
    _name = "cc.disposition"
    _description = "Canonical Campaign Disposition"
    _inherits = {"codestra.disposition": "legacy_disposition_id"}
    _order = "cc_campaign_id, native_status_code"

    legacy_disposition_id = fields.Many2one(
        "codestra.disposition", required=True, ondelete="restrict", index=True, copy=False
    )
    set_id = fields.Many2one(
        "cc.disposition.set", required=True, ondelete="restrict", index=True, copy=False
    )
    cc_campaign_id = fields.Many2one(
        "cc.campaign",
        string="Canonical Campaign Workspace",
        related="set_id.campaign_id",
        store=True,
        readonly=True,
        index=True,
    )
    channel_id = fields.Many2one(
        "cc.campaign.channel", required=True, ondelete="restrict", index=True, copy=False
    )
    native_status_code = fields.Char(
        string="Native VICIdial Status",
        related="legacy_disposition_id.vicidial_status_code",
        store=True,
        readonly=True,
        index=True,
    )
    required_fields_json = fields.Json(default=list, readonly=True)
    callback_behavior = fields.Selection(
        [("none", "None"), ("required", "Required"), ("optional", "Optional")],
        required=True,
        default="none",
        readonly=True,
    )
    suppression_behavior = fields.Selection(
        [
            ("none", "None"),
            ("campaign", "Campaign"),
            ("entity", "Entity"),
            ("campaign_and_entity", "Campaign and Entity"),
        ],
        required=True,
        default="none",
        readonly=True,
    )
    reporting_category = fields.Char(required=True, readonly=True, index=True)
    event_name = fields.Char(required=True, readonly=True, index=True)
    workflow_mapping_json = fields.Json(default=dict, readonly=True)
    catalog_row_sha256 = fields.Char(required=True, size=64, readonly=True, index=True)
    source_catalog_sha256 = fields.Char(
        related="set_id.catalog_sha256", store=True, readonly=True, index=True
    )

    _legacy_disposition_unique = models.Constraint(
        "unique(legacy_disposition_id)",
        "A legacy disposition may be adopted only once.",
    )
    _set_channel_status_unique = models.Constraint(
        "unique(set_id, channel_id, native_status_code)",
        "Native status codes must be unique per disposition set and channel.",
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get(
            "_cc_disposition_catalog_capability"
        ) is not DISPOSITION_CATALOG_CAPABILITY:
            raise AccessError(_("Dispositions require the controlled catalog importer."))
        for values in values_list:
            self._validate_catalog_values(values)
        records = super().create(values_list)
        records._check_catalog_identity()
        return records

    @api.model
    def _validate_catalog_values(self, values):
        legacy = self.env["codestra.disposition"].browse(
            values.get("legacy_disposition_id")
        ).exists()
        disposition_set = self.env["cc.disposition.set"].browse(
            values.get("set_id")
        ).exists()
        channel = self.env["cc.campaign.channel"].browse(
            values.get("channel_id")
        ).exists()
        if not legacy or not disposition_set or not channel:
            raise ValidationError(
                _("A controlled row requires an existing legacy row, set, and channel.")
            )
        if disposition_set.state != "draft":
            raise ValidationError(_("Only a draft disposition set can receive rows."))
        if channel.campaign_id != disposition_set.campaign_id:
            raise ValidationError(_("Disposition channel and set must share a campaign."))
        if legacy.campaign_id != disposition_set.campaign_id.legacy_campaign_id:
            raise ValidationError(_("Legacy and canonical dispositions must share a campaign."))
        if not re.fullmatch(r"[A-Z0-9]{1,6}", legacy.vicidial_status_code or ""):
            raise ValidationError(
                _("VICIdial status codes must be one to six uppercase characters.")
            )
        if not SHA256_PATTERN.fullmatch(
            str(values.get("catalog_row_sha256") or "").lower()
        ):
            raise ValidationError(_("Disposition rows require a SHA-256 source hash."))
        if not EVENT_NAME_PATTERN.fullmatch(str(values.get("event_name") or "")):
            raise ValidationError(_("Disposition event names must be versioned cc events."))
        if legacy.callback_required and values.get("callback_behavior", "none") == "none":
            raise ValidationError(_("Callback dispositions require callback behavior."))

    def write(self, values):
        if self.env.context.get(
            "_cc_disposition_catalog_capability"
        ) is not DISPOSITION_CATALOG_CAPABILITY:
            raise AccessError(_("Controlled dispositions are immutable."))
        result = super().write(values)
        self._check_catalog_identity()
        return result

    def unlink(self):
        raise AccessError(_("Controlled dispositions are deactivated, never deleted."))

    def copy(self, default=None):
        raise AccessError(_("Controlled disposition rows cannot be copied."))

    def export_data(self, fields_to_export, raw_data=False):
        if _is_operational_user(self.env.user):
            raise UserError(_("Agent and supervisor disposition export is disabled."))
        return super().export_data(fields_to_export, raw_data=raw_data)

    @api.constrains(
        "legacy_disposition_id",
        "set_id",
        "channel_id",
        "native_status_code",
        "catalog_row_sha256",
        "event_name",
        "callback_behavior",
    )
    def _check_catalog_identity(self):
        for disposition in self:
            if disposition.set_id.state != "draft":
                raise ValidationError(_("Only a draft disposition set can receive rows."))
            if disposition.channel_id.campaign_id != disposition.cc_campaign_id:
                raise ValidationError(_("Disposition channel and set must share a campaign."))
            if disposition.legacy_disposition_id.campaign_id != disposition.cc_campaign_id.legacy_campaign_id:
                raise ValidationError(_("Legacy and canonical dispositions must share a campaign."))
            if not re.fullmatch(r"[A-Z0-9]{1,6}", disposition.native_status_code or ""):
                raise ValidationError(
                    _("VICIdial status codes must be one to six uppercase characters.")
                )
            if not SHA256_PATTERN.fullmatch(
                str(disposition.catalog_row_sha256 or "").lower()
            ):
                raise ValidationError(_("Disposition rows require a SHA-256 source hash."))
            if not EVENT_NAME_PATTERN.fullmatch(str(disposition.event_name or "")):
                raise ValidationError(_("Disposition event names must be versioned cc events."))
            if disposition.callback_required and disposition.callback_behavior == "none":
                raise ValidationError(_("Callback dispositions require callback behavior."))


class CallCenterScriptGovernance(models.Model):
    _inherit = "call.center.script"

    prohibited_statements = fields.Html(
        groups=(
            "codestra_cc_security.group_cc_campaign_configuration_manager,"
            "codestra_cc_security.group_cc_global_administrator,"
            "codestra_cc_security.group_cc_auditor"
        )
    )
    supervisor_notes = fields.Html(
        groups=(
            "codestra_cc_security.group_cc_campaign_configuration_manager,"
            "codestra_cc_security.group_cc_global_administrator,"
            "codestra_cc_security.group_cc_auditor"
        )
    )

    def write(self, values):
        governed = self.env["cc.script.version"].search(
            [("legacy_script_id", "in", self.ids)]
        )
        if governed and SCRIPT_IDENTITY_FIELDS.intersection(values):
            if self.env.context.get(
                "_cc_script_version_capability"
            ) is not SCRIPT_VERSION_CAPABILITY:
                raise AccessError(_("Adopted script identity is immutable."))
        if governed and set(values).intersection(set(SCRIPT_CONTENT_FIELDS) | {"state"}):
            if any(version.governance_state != "draft" for version in governed) and self.env.context.get(
                "_cc_script_version_capability"
            ) is not SCRIPT_VERSION_CAPABILITY:
                raise AccessError(_("Reviewed script content is immutable."))
        return super().write(values)

    def unlink(self):
        if self.env["cc.script.version"].search_count(
            [("legacy_script_id", "in", self.ids)], limit=1
        ):
            raise AccessError(_("Adopted script versions cannot be deleted."))
        return super().unlink()

    def copy(self, default=None):
        if self.env["cc.script.version"].search_count(
            [("legacy_script_id", "in", self.ids)], limit=1
        ):
            raise AccessError(_("Use the governed script-version workflow."))
        return super().copy(default)


class CodestraDispositionGovernance(models.Model):
    _inherit = "codestra.disposition"

    def write(self, values):
        if DISPOSITION_SOURCE_FIELDS.intersection(values) and self.env[
            "cc.disposition"
        ].search_count([("legacy_disposition_id", "in", self.ids)], limit=1):
            if self.env.context.get(
                "_cc_disposition_catalog_capability"
            ) is not DISPOSITION_CATALOG_CAPABILITY:
                raise AccessError(_("Controlled catalog dispositions are immutable."))
        return super().write(values)

    def unlink(self):
        if self.env["cc.disposition"].search_count(
            [("legacy_disposition_id", "in", self.ids)], limit=1
        ):
            raise AccessError(_("Controlled catalog dispositions cannot be deleted."))
        return super().unlink()

    def copy(self, default=None):
        if self.env["cc.disposition"].search_count(
            [("legacy_disposition_id", "in", self.ids)], limit=1
        ):
            raise AccessError(_("Controlled catalog dispositions cannot be copied."))
        return super().copy(default)
