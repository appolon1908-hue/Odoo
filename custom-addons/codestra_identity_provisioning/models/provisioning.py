import hashlib
import json
import re
import unicodedata
import urllib.parse
import uuid
from datetime import datetime, timezone

from psycopg2 import IntegrityError
from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


SAFE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}$")
SECRET_FIELD_NAMES = {
    "password", "secret", "secret_value", "token", "api_token", "private_key",
    "turn_secret", "sip_password",
}
SAFETY_FLAGS = (
    "send_events", "production_callbacks_enabled", "vicidial_writes_enabled",
    "external_dial_enabled", "transfers_enabled",
    "n8n_production_workflows_enabled", "webrtc_production_routes_enabled",
    "allow_live_email", "allow_live_sms", "allow_live_calls",
    "allow_campaign_activation",
)
DEFAULT_ROLE_POLICIES = {
    "AGENT": {},
    "CLOSER": {},
    "SUPERVISOR": {"allows_monitoring": True},
    "QA_REVIEWER": {"allows_recordings": True, "requires_compliance_approval": True},
    "CAMPAIGN_MANAGER": {"requires_compliance_approval": True},
    "COMPLIANCE": {"allows_recordings": True, "requires_compliance_approval": True},
    "AUDITOR": {"allows_recordings": True, "requires_security_approval": True},
    "SYSTEM_ADMIN": {"requires_security_approval": True},
    "INTEGRATION_SERVICE": {"requires_security_approval": True},
}


def sanitized_error(error):
    """Return a bounded error category; never persist exception payloads."""
    return "%s: operation failed; inspect protected server logs" % (
        error.__class__.__name__[:64]
    )


def normalize_identifier(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.lower().replace("'", "")
    return re.sub(r"[^a-z0-9]+", ".", value).strip(".")


class ProvisioningInboundGroup(models.Model):
    _name = "codestra.provisioning.inbound.group"
    _description = "Approved VICIdial Inbound Group"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    business_unit_id = fields.Many2one(
        "call.center.business.unit", required=True, ondelete="restrict", index=True
    )
    external_reference = fields.Char(required=True, copy=False)
    active = fields.Boolean(default=True)

    _code_unique = models.Constraint(
        "unique(code)", "Inbound-group codes must be globally unique."
    )


class RoleTemplate(models.Model):
    _name = "codestra.role.template"
    _description = "Versioned Least-Privilege Role Template"
    _inherit = ["mail.thread", "call.center.business.unit.mixin"]
    _order = "code, version desc"

    code = fields.Char(required=True, index=True, tracking=True)
    name = fields.Char(required=True, tracking=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    odoo_group_ids = fields.Many2many("res.groups", string="Odoo Groups")
    keycloak_group_paths = fields.Text()
    keycloak_realm_roles = fields.Text()
    keycloak_client_roles = fields.Text()
    vicidial_user_group = fields.Char()
    vicidial_campaign_profile = fields.Char()
    vicidial_inbound_group_profile = fields.Char()
    agent_desktop_roles = fields.Text()
    requires_email = fields.Boolean()
    requires_phone = fields.Boolean()
    requires_mfa = fields.Boolean(default=True)
    allows_recordings = fields.Boolean()
    allows_monitoring = fields.Boolean()
    allows_whisper = fields.Boolean()
    allows_barge = fields.Boolean()
    allows_transfer = fields.Boolean()
    requires_compliance_approval = fields.Boolean()
    requires_security_approval = fields.Boolean()
    conflicting_template_ids = fields.Many2many(
        "codestra.role.template",
        "codestra_role_template_conflict_rel",
        "template_id",
        "conflict_id",
    )
    version = fields.Integer(required=True, default=1, readonly=True)
    active = fields.Boolean(default=True, tracking=True)

    _version_unique = models.Constraint(
        "unique(code, version, business_unit_id)",
        "Role-template code and version must be unique within a business unit."
    )

    def write(self, values):
        privilege_fields = {
            "odoo_group_ids", "keycloak_group_paths", "keycloak_realm_roles",
            "keycloak_client_roles", "vicidial_user_group",
            "vicidial_campaign_profile", "vicidial_inbound_group_profile",
            "agent_desktop_roles", "requires_email", "requires_phone",
            "requires_mfa", "allows_recordings", "allows_monitoring",
            "allows_whisper", "allows_barge", "allows_transfer",
            "requires_compliance_approval", "requires_security_approval",
            "conflicting_template_ids",
        }
        if privilege_fields.intersection(values) and not self.env.context.get(
            "role_template_version_write"
        ):
            for template in self:
                next_values = dict(
                    values,
                    code=template.code,
                    version=template.version + 1,
                    active=True,
                )
                template.with_context(role_template_version_write=True).write(
                    {"active": False}
                )
                template.copy(next_values)
            return True
        return super().write(values)


class CredentialReference(models.Model):
    _name = "codestra.credential.reference"
    _description = "Protected Credential Metadata Reference"
    _order = "create_date desc"

    name = fields.Char(required=True)
    system = fields.Char(required=True, index=True, string="Provider")
    secret_backend = fields.Selection(
        [("vault", "Vault"), ("protected_file", "Protected File"),
         ("cloud_kms", "Cloud KMS"), ("other", "Other")],
        required=True,
    )
    secret_path = fields.Char(required=True, copy=False, string="Protected Path", groups=
        "codestra_identity_provisioning.group_provisioning_security_admin")
    key_id = fields.Char(copy=False)
    version = fields.Char(copy=False)
    fingerprint = fields.Char(required=True, copy=False)
    owner = fields.Char(required=True)
    created_at = fields.Datetime(default=fields.Datetime.now, required=True)
    expires_at = fields.Datetime()
    rotated_at = fields.Datetime()
    revoked_at = fields.Datetime()
    state = fields.Selection(
        [("active", "Active"), ("rotation_due", "Rotation Due"),
         ("expired", "Expired"), ("revoked", "Revoked")],
        default="active", required=True,
    )

    @api.constrains("secret_path", "fingerprint")
    def _check_protected_metadata(self):
        for record in self:
            if not SAFE_REFERENCE.fullmatch(record.secret_path or ""):
                raise ValidationError("Only protected secret references are allowed.")
            if len(record.fingerprint or "") < 16:
                raise ValidationError("Credential fingerprints must be non-trivial.")

    def export_data(self, fields_to_export):
        if not self.env.user.has_group(
            "codestra_identity_provisioning.group_provisioning_security_admin"
        ):
            raise AccessError("Credential metadata export is restricted.")
        return super().export_data(fields_to_export)


class ExtensionPool(models.Model):
    _name = "codestra.extension.pool"
    _description = "SIP Extension Allocation Pool"
    _inherit = "call.center.business.unit.mixin"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    start_extension = fields.Integer(required=True)
    end_extension = fields.Integer(required=True)
    technology = fields.Selection(
        [("pjsip", "PJSIP"), ("sip", "SIP")], default="pjsip", required=True
    )
    context = fields.Char(required=True)
    wss_server = fields.Char()
    default_expiration_seconds = fields.Integer(default=300, required=True)
    one_user_one_endpoint = fields.Boolean(default=True)
    active = fields.Boolean(default=False)

    _code_unique = models.Constraint(
        "unique(code)", "Extension-pool codes must be unique."
    )

    @api.constrains("start_extension", "end_extension")
    def _check_range(self):
        for pool in self:
            if pool.start_extension > pool.end_extension:
                raise ValidationError("Extension-pool range is invalid.")
            if pool.start_extension < 100 or pool.end_extension > 999999:
                raise ValidationError("Extension-pool range is outside policy.")

    def reserve_extension(self, employee, request):
        self.ensure_one()
        if not self.active:
            raise UserError("The extension pool is not verified and active.")
        self.env.cr.execute("SELECT id FROM codestra_extension_pool WHERE id=%s FOR UPDATE", [self.id])
        self.env.cr.execute(
            """
            SELECT candidate
              FROM generate_series(%s, %s) candidate
             WHERE candidate <> 6101
               AND NOT EXISTS (
                    SELECT 1 FROM codestra_extension_assignment a
                     WHERE a.extension = candidate::varchar
                       AND a.state IN ('reserved', 'committed')
               )
             ORDER BY candidate
             LIMIT 1
            """,
            [self.start_extension, self.end_extension],
        )
        row = self.env.cr.fetchone()
        if not row:
            raise UserError("The extension pool is exhausted.")
        return self.env["codestra.extension.assignment"].create({
            "pool_id": self.id,
            "extension": str(row[0]),
            "employee_id": employee.id,
            "request_id": request.id,
            "state": "reserved",
            "reserved_at": fields.Datetime.now(),
            "expires_at": fields.Datetime.add(
                fields.Datetime.now(), seconds=self.default_expiration_seconds
            ),
        })


class ExtensionAssignment(models.Model):
    _name = "codestra.extension.assignment"
    _description = "SIP Extension Assignment"

    pool_id = fields.Many2one(
        "codestra.extension.pool", required=True, ondelete="restrict", index=True
    )
    extension = fields.Char(required=True, index=True)
    employee_id = fields.Many2one("hr.employee", required=True, ondelete="restrict")
    request_id = fields.Many2one(
        "codestra.provisioning.request", required=True, ondelete="restrict"
    )
    state = fields.Selection(
        [("reserved", "Reserved"), ("committed", "Committed"),
         ("released", "Released"), ("expired", "Expired")],
        default="reserved", required=True,
    )
    reserved_at = fields.Datetime(required=True)
    expires_at = fields.Datetime()
    committed_at = fields.Datetime()
    released_at = fields.Datetime()
    endpoint_external_id = fields.Char(copy=False)

    _extension_unique = models.Constraint(
        "unique(extension)", "An extension may have only one assignment record."
    )
    _extension_6101_excluded = models.Constraint(
        "CHECK (extension <> '6101')", "Extension 6101 is reserved from allocation."
    )


class EmailDomain(models.Model):
    _name = "codestra.email.domain"
    _description = "Managed Email Domain"

    domain = fields.Char(required=True, index=True)
    provider_type = fields.Selection(
        [("google_workspace", "Google Workspace"),
         ("microsoft_365", "Microsoft 365"), ("cpanel", "cPanel"),
         ("whm", "WHM"), ("hosted_mail", "Hosted Mail"),
         ("custom_api", "Custom API")],
        required=True,
    )
    provider_tenant_reference = fields.Char(required=True)
    credential_reference_id = fields.Many2one(
        "codestra.credential.reference", required=True, ondelete="restrict"
    )
    default_alias_policy = fields.Char()
    license_policy = fields.Char()
    business_unit_ids = fields.Many2many("call.center.business.unit")
    active = fields.Boolean(default=True)

    _domain_unique = models.Constraint(
        "unique(domain)", "Email domains must be unique."
    )


class CompanyMailbox(models.Model):
    _name = "codestra.company.mailbox"
    _description = "Company Mailbox Provisioning Projection"
    _order = "email_address"

    email_address = fields.Char(required=True, copy=False, index=True)
    provider = fields.Char(required=True, copy=False, index=True)
    external_mailbox_id = fields.Char(required=True, copy=False, index=True)
    aliases = fields.Json(default=list, copy=False)
    provisioning_state = fields.Selection(
        [
            ("reserved", "Reserved"),
            ("disabled", "Disabled"),
            ("awaiting_activation", "Awaiting Activation"),
            ("active", "Active"),
            ("suspended", "Suspended"),
            ("terminated", "Terminated"),
            ("error", "Error"),
        ],
        required=True,
        default="reserved",
        copy=False,
        index=True,
    )
    created_at = fields.Datetime(required=True, default=fields.Datetime.now)
    activated_at = fields.Datetime(copy=False)
    suspended_at = fields.Datetime(copy=False)
    terminated_at = fields.Datetime(copy=False)
    credential_reference = fields.Many2one(
        "codestra.credential.reference", required=True, ondelete="restrict",
        copy=False,
    )

    _email_unique = models.Constraint(
        "unique(email_address)", "A company email address may be provisioned once."
    )
    _external_id_unique = models.Constraint(
        "unique(provider, external_mailbox_id)",
        "A provider mailbox may be projected once.",
    )

    @api.constrains("aliases")
    def _check_aliases(self):
        for mailbox in self:
            aliases = mailbox.aliases or []
            if not isinstance(aliases, list) or any(
                not isinstance(alias, str) or "@" not in alias
                for alias in aliases
            ):
                raise ValidationError("Mailbox aliases must be email-address strings.")
            if len(aliases) != len(set(alias.lower() for alias in aliases)):
                raise ValidationError("Mailbox aliases must be unique.")


class IdentifierReservation(models.Model):
    _name = "codestra.identifier.reservation"
    _description = "Concurrent-Safe Identifier Reservation"

    identifier_type = fields.Selection(
        [("employee_id", "Employee ID"), ("email", "Email"),
         ("keycloak_username", "Keycloak Username"),
         ("vicidial_username", "VICIdial Username"),
         ("sip_extension", "SIP Extension")],
        required=True,
    )
    normalized_value = fields.Char(required=True, index=True)
    request_id = fields.Many2one(
        "codestra.provisioning.request", required=True, ondelete="restrict"
    )
    state = fields.Selection(
        [("reserved", "Reserved"), ("committed", "Committed"),
         ("released", "Released"), ("expired", "Expired")],
        default="reserved", required=True,
    )
    reserved_at = fields.Datetime(default=fields.Datetime.now, required=True)
    expires_at = fields.Datetime()
    committed_at = fields.Datetime()
    released_at = fields.Datetime()

    _identifier_unique = models.Constraint(
        "unique(identifier_type, normalized_value)",
        "This normalized identifier is already reserved.",
    )

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            values["normalized_value"] = normalize_identifier(
                values.get("normalized_value")
            )
        return super().create(values_list)


class IdentityLink(models.Model):
    _name = "codestra.identity.link"
    _description = "External Identity Link"
    _inherit = "call.center.business.unit.mixin"

    employee_id = fields.Many2one("hr.employee", required=True, ondelete="restrict")
    system = fields.Selection(
        [("odoo", "Odoo"), ("keycloak", "Keycloak"), ("email", "Email"),
         ("vicidial", "VICIdial"), ("sip", "SIP"),
         ("voicemail", "Voicemail"), ("recording", "Recording"),
         ("monitoring", "Monitoring"),
         ("agent_desktop", "Agent Desktop")],
        required=True,
    )
    provider = fields.Char()
    external_id = fields.Char(required=True, copy=False, index=True)
    external_username = fields.Char(copy=False)
    email_address = fields.Char(copy=False)
    extension = fields.Char(copy=False)
    endpoint_id = fields.Char(copy=False)
    state = fields.Selection(
        [("pending", "Pending"), ("active", "Active"),
         ("suspended", "Suspended"), ("terminated", "Terminated")],
        default="pending", required=True,
    )
    is_primary = fields.Boolean(default=True)
    credential_reference_id = fields.Many2one(
        "codestra.credential.reference", ondelete="restrict"
    )
    created_at = fields.Datetime(default=fields.Datetime.now, required=True)
    verified_at = fields.Datetime()
    disabled_at = fields.Datetime()
    terminated_at = fields.Datetime()
    last_reconciled_at = fields.Datetime()
    drift_state = fields.Selection(
        [("aligned", "Aligned"),
         ("missing_external_identity", "Missing External Identity"),
         ("unexpected_external_identity", "Unexpected External Identity"),
         ("privilege_drift", "Privilege Drift"),
         ("campaign_drift", "Campaign Drift"),
         ("disabled_state_mismatch", "Disabled State Mismatch"),
         ("orphaned_endpoint", "Orphaned Endpoint"),
         ("expired_credential", "Expired Credential"),
         ("secret_rotation_due", "Secret Rotation Due"),
         ("mailbox_state_mismatch", "Mailbox State Mismatch")],
        default="aligned", required=True,
    )

    _external_identity_unique = models.Constraint(
        "unique(system, provider, external_id)",
        "External identities cannot be assigned to multiple employees.",
    )
    @api.constrains("employee_id", "system", "state", "is_primary")
    def _check_primary_sip(self):
        for link in self.filtered(
            lambda item: item.system == "sip"
            and item.state == "active"
            and item.is_primary
        ):
            duplicate = self.search_count([
                ("id", "!=", link.id),
                ("employee_id", "=", link.employee_id.id),
                ("system", "=", "sip"),
                ("state", "=", "active"),
                ("is_primary", "=", True),
            ])
            if duplicate:
                raise ValidationError(
                    "An employee may have only one active primary SIP endpoint."
                )

    def _set_lifecycle_state(self, state):
        if state not in ("active", "suspended", "terminated"):
            raise ValidationError("Unsupported identity lifecycle state.")
        now = fields.Datetime.now()
        values = {"state": state}
        if state == "active":
            values.update({
                "disabled_at": False,
                "terminated_at": False,
                "verified_at": now,
            })
        else:
            values[
                "disabled_at" if state == "suspended" else "terminated_at"
            ] = now
        return self.write(values)


REQUEST_STATES = [
    ("draft", "Draft"), ("pending_approval", "Pending Approval"),
    ("approved", "Approved"), ("reserving", "Reserving"),
    ("provisioning", "Provisioning"),
    ("partially_provisioned", "Partially Provisioned"),
    ("verification", "Verification"),
    ("awaiting_user_activation", "Awaiting User Activation"),
    ("active", "Active"), ("suspended", "Suspended"),
    ("termination_pending", "Termination Pending"),
    ("terminated", "Terminated"), ("failed", "Failed"),
    ("cancelled", "Cancelled"),
]


class ProvisioningRequest(models.Model):
    _name = "codestra.provisioning.request"
    _description = "Identity Provisioning Request"
    _inherit = ["mail.thread", "mail.activity.mixin", "call.center.business.unit.mixin"]
    _order = "create_date desc"

    request_number = fields.Char(
        required=True, copy=False, readonly=True, default=lambda self: self.env[
            "ir.sequence"].next_by_code("codestra.provisioning.request")
    )
    request_type = fields.Selection(
        [("onboard", "Onboard"), ("change_access", "Change Access"),
         ("change_campaign", "Change Campaign"),
         ("change_supervisor", "Change Supervisor"),
         ("suspend", "Suspend"), ("reactivate", "Reactivate"),
         ("terminate", "Terminate"),
         ("rotate_credentials", "Rotate Credentials")],
        required=True, default="onboard",
    )
    state = fields.Selection(REQUEST_STATES, default="draft", required=True, tracking=True)
    employee_id = fields.Many2one("hr.employee", required=True, ondelete="restrict")
    personal_email = fields.Char()
    recovery_phone = fields.Char()
    requested_by = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user
    )
    requested_for = fields.Many2one("res.users")
    supervisor_id = fields.Many2one("res.users", required=True)
    approval_owner_id = fields.Many2one("res.users")
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    branch_id = fields.Many2one("call.center.branch", ondelete="restrict", index=True)
    department_id = fields.Many2one(
        "call.center.department", required=True, ondelete="restrict"
    )
    operational_team_id = fields.Many2one(
        "call.center.team", required=True, ondelete="restrict"
    )
    role_template_id = fields.Many2one(
        "codestra.role.template", required=True, ondelete="restrict"
    )
    role_template_version = fields.Integer(related="role_template_id.version", store=True)
    primary_campaign_id = fields.Many2one(
        "call.center.campaign", string="Campaign", ondelete="restrict", index=True
    )
    campaign_ids = fields.Many2many("call.center.campaign")
    extension_pool_id = fields.Many2one(
        "codestra.extension.pool", string="Extension Pool", ondelete="restrict"
    )
    inbound_group_ids = fields.Many2many(
        "codestra.provisioning.inbound.group",
        "codestra_request_inbound_group_rel",
        "request_id",
        "inbound_group_id",
    )
    start_date = fields.Date(required=True)
    termination_date = fields.Date()
    preferred_language = fields.Selection(
        selection=lambda self: self.env["res.lang"].get_installed()
    )
    country_id = fields.Many2one("res.country")
    timezone = fields.Selection(
        selection=lambda self: self.env["res.users"]._fields["tz"]._description_selection(self.env),
        default=lambda self: self.env.user.tz or "UTC",
    )
    employment_status = fields.Selection(
        [("pending", "Pending"), ("active", "Active"),
         ("suspended", "Suspended"), ("terminated", "Terminated")],
        required=True, default="pending",
    )
    work_location = fields.Char()
    work_schedule_id = fields.Many2one("resource.calendar")
    calling_hours_policy_id = fields.Char()
    needs_company_email = fields.Boolean()
    needs_sip_endpoint = fields.Boolean()
    needs_voicemail = fields.Boolean()
    needs_recording_access = fields.Boolean()
    needs_monitoring_access = fields.Boolean()
    needs_agent_desktop = fields.Boolean(default=True)
    needs_keycloak = fields.Boolean(default=True)
    needs_vicidial = fields.Boolean(default=True)
    idempotency_key = fields.Char(required=True, copy=False, index=True)
    correlation_id = fields.Char(
        required=True, copy=False, index=True, default=lambda self: str(uuid.uuid4())
    )
    activation_deadline = fields.Datetime()
    mandatory_steps_complete = fields.Boolean(compute="_compute_mandatory_steps")
    last_error_code = fields.Char(copy=False)
    last_error_sanitized = fields.Text(copy=False)
    step_ids = fields.One2many("codestra.provisioning.step", "request_id")
    operational_approved = fields.Boolean()
    compliance_approved = fields.Boolean()
    security_approved = fields.Boolean()
    it_approved = fields.Boolean()
    audit_ids = fields.One2many(
        "codestra.provisioning.audit", "request_id", readonly=True
    )
    drift_state = fields.Selection(
        [("not_checked", "Not Checked"), ("aligned", "Aligned"),
         ("drift_detected", "Drift Detected"), ("reconciling", "Reconciling"),
         ("reconciliation_failed", "Reconciliation Failed")],
        default="not_checked", required=True, copy=False,
    )
    last_reconciled_at = fields.Datetime(copy=False)

    _request_number_unique = models.Constraint(
        "unique(request_number)", "Provisioning request numbers must be unique."
    )
    _idempotency_unique = models.Constraint(
        "unique(idempotency_key)", "Provisioning idempotency keys must be unique."
    )
    _correlation_unique = models.Constraint(
        "unique(correlation_id)", "Provisioning correlation IDs must be unique."
    )

    @api.model_create_multi
    def create(self, values_list):
        records = self.browse()
        for values in values_list:
            if not values.get("idempotency_key"):
                seed = "|".join(str(values.get(key) or "") for key in (
                    "request_type", "employee_id", "company_id", "business_unit_id",
                    "role_template_id", "start_date", "termination_date",
                ))
                values["idempotency_key"] = hashlib.sha256(seed.encode()).hexdigest()
            existing = self.search(
                [("idempotency_key", "=", values.get("idempotency_key"))], limit=1
            )
            record = existing or super().create([values])
            records |= record
            if not existing:
                record._audit("request.created", "accepted", after={
                    "request_type": record.request_type, "state": record.state,
                })
        return records

    def write(self, values):
        if {"correlation_id", "idempotency_key"}.intersection(values):
            raise ValidationError(
                "Correlation IDs and idempotency keys are immutable."
            )
        tracked = {"state", "employee_id", "business_unit_id", "role_template_id"}
        before = {
            record.id: {key: record[key].id if hasattr(record[key], "id")
                        else record[key] for key in tracked.intersection(values)}
            for record in self
        }
        result = super().write(values)
        for record in self:
            if tracked.intersection(values):
                record._audit(
                    "request.updated", "accepted", before=before[record.id],
                    after={key: record[key].id if hasattr(record[key], "id")
                           else record[key] for key in tracked.intersection(values)},
                )
        return result

    def unlink(self):
        if any(record.state != "draft" for record in self):
            raise AccessError("Only draft provisioning requests may be deleted.")
        return super().unlink()

    def _audit(self, event_type, result, before=None, after=None, step=None):
        self.ensure_one()
        return self.env["codestra.provisioning.audit"].sudo().create({
            "request_id": self.id,
            "step_id": step.id if step else False,
            "event_type": event_type,
            "actor_id": self.env.user.id,
            "actor_system": "odoo",
            "correlation_id": self.correlation_id,
            "sanitized_before": before,
            "sanitized_after": after,
            "result": result,
        })

    @api.model
    def assert_safe_mode(self):
        parameters = self.env["ir.config_parameter"].sudo()
        enabled = [
            name for name in SAFETY_FLAGS
            if parameters.get_param(
                "codestra.provisioning.%s" % name, "false"
            ).lower() not in ("false", "0", "no", "off")
        ]
        if enabled:
            raise UserError(
                "Provisioning is fail-closed because a production route is enabled."
            )
        return True

    def _reserve_identifier(
        self, identifier_type, base, max_length=None, suffix_separator="."
    ):
        self.ensure_one()
        reservation_model = self.env["codestra.identifier.reservation"]
        normalized = normalize_identifier(base)
        for suffix in range(0, 10000):
            suffix_value = (
                "" if not suffix else "%s%s" % (suffix_separator, suffix + 1)
            )
            base_limit = (
                max_length - len(suffix_value) if max_length is not None else None
            )
            candidate = normalized[:base_limit] + suffix_value
            try:
                with self.env.cr.savepoint():
                    return reservation_model.create({
                        "identifier_type": identifier_type,
                        "normalized_value": candidate,
                        "request_id": self.id,
                    })
            except IntegrityError:
                continue
        raise UserError("Identifier namespace is exhausted.")

    def action_reserve_identifiers(self):
        for request in self:
            if request.state not in ("approved", "failed"):
                raise UserError("Only approved or failed requests can reserve identifiers.")
            request.assert_safe_mode()
            request.state = "reserving"
            employee_base = normalize_identifier(request.employee_id.name)
            unit_code = normalize_identifier(request.business_unit_id.code)
            year = (request.start_date or fields.Date.today()).year
            employee_number = "%s-%s-%05d" % (
                request.business_unit_id.code.upper(), year, request.employee_id.id
            )
            identifiers = {
                "employee_id": employee_number,
                "keycloak_username": employee_base,
                "vicidial_username": "%s%05d" % (
                    unit_code.replace(".", "").replace("-", "")[:3],
                    request.employee_id.id,
                ),
            }
            if request.needs_company_email:
                identifiers["email"] = employee_base
            existing_types = set(request.env["codestra.identifier.reservation"].search([
                ("request_id", "=", request.id),
                ("state", "in", ("reserved", "committed")),
            ]).mapped("identifier_type"))
            for kind, base in identifiers.items():
                if kind not in existing_types:
                    request._reserve_identifier(
                        kind, base, max_length=20
                        if kind == "vicidial_username" else None,
                        suffix_separator=""
                        if kind == "vicidial_username" else ".",
                    )
            employee_reservation = request.env["codestra.identifier.reservation"].search([
                ("request_id", "=", request.id),
                ("identifier_type", "=", "employee_id"),
            ], limit=1)
            if not request.employee_id.codestra_employee_number:
                request.employee_id.codestra_employee_number = (
                    employee_reservation.normalized_value.upper()
                )
            request._ensure_steps()
            request.state = "provisioning"
            request._audit("identifiers.reserved", "accepted")
        return True

    def _ensure_steps(self):
        for request in self:
            operations = [("odoo", "upsert_user")]
            if request.needs_keycloak:
                operations.append(("keycloak", "upsert_identity"))
            if request.needs_company_email:
                operations.append(("email", "upsert_mailbox"))
            if request.needs_vicidial:
                operations.append(("vicidial", "upsert_agent"))
            if request.needs_sip_endpoint:
                operations.append(("sip", "upsert_endpoint"))
            if request.needs_agent_desktop:
                operations.append(("agent_desktop", "assign_roles"))
            if request.needs_voicemail:
                operations.append(("voicemail", "provision_mailbox"))
            if request.needs_recording_access:
                operations.append(("recording_access", "grant_access"))
            if request.needs_monitoring_access:
                operations.append(("monitoring_access", "grant_access"))
            operations.append(("verification", "verify_all"))
            for sequence, (system, operation) in enumerate(operations, 1):
                key = hashlib.sha256(
                    ("%s:%s:%s" % (
                        request.idempotency_key, system, operation
                    )).encode()
                ).hexdigest()
                if not self.env["codestra.provisioning.step"].search_count([
                    ("idempotency_key", "=", key),
                ]):
                    self.env["codestra.provisioning.step"].create({
                        "request_id": request.id,
                        "sequence": sequence * 10,
                        "target_system": system,
                        "operation": operation,
                        "idempotency_key": key,
                    })

    def action_retry_failed_steps(self):
        if not self.env.su and not (
            self.env.user.has_group(
                "codestra_identity_provisioning.group_provisioning_approver"
            )
            or self.env.user.has_group(
                "codestra_identity_provisioning.group_provisioning_service"
            )
        ):
            raise AccessError("Provisioning retry permission is required.")
        for request in self:
            failed = request.step_ids.filtered(
                lambda step: step.state == "failed" and step.retryable
                and step.attempt_count < step.max_attempts
            )
            if not failed:
                raise UserError("There are no retryable failed steps.")
            failed.write({
                "state": "retry_scheduled",
                "last_error_code": False,
                "last_error_sanitized": False,
            })
            request.state = "provisioning"
            request._audit("steps.retry_scheduled", "accepted", after={
                "step_ids": failed.ids,
            })
        return True

    @api.model
    def apply_service_callback(self, payload):
        required = {
            "event_id", "request_id", "correlation_id", "state",
            "step_results", "timestamp",
        }
        allowed_payload = required | {
            "schema_version", "employee_id", "idempotency_key",
            "target_system", "operation",
        }
        if (
            not required <= set(payload)
            or set(payload) - allowed_payload
            or not isinstance(payload["step_results"], list)
        ):
            raise ValueError("invalid_callback_schema")
        event_type = "service.callback.%s" % payload["event_id"]
        if self.env["codestra.provisioning.audit"].sudo().search_count([
            ("event_type", "=", event_type),
        ]):
            return {"state": "replayed"}
        request_match = re.match(
            r"^([0-9]+)(?:[-:].*)?$", str(payload["request_id"])
        )
        if not request_match:
            raise ValueError("invalid_request_id")
        provision_request = self.search([
            ("id", "=", int(request_match.group(1))),
        ], limit=1)
        correlation = payload["correlation_id"]
        if (
            not provision_request
            or (
                correlation != provision_request.correlation_id
                and not correlation.startswith(
                    provision_request.correlation_id + ":"
                )
            )
        ):
            raise ValueError("request_not_found")
        state_map = {
            "completed": "awaiting_user_activation",
            "dead_letter": "partially_provisioned",
            "retry_wait": "partially_provisioned",
            "running": "provisioning",
            "pending": "provisioning",
        }
        state = state_map.get(payload["state"], payload["state"])
        if state not in {
            "partially_provisioned", "failed", "verification",
            "awaiting_user_activation", "active", "provisioning",
        }:
            raise ValueError("invalid_state")
        target_map = {
            "email_provider": "email",
            "secret_storage": "secret_store",
            "reconciliation": "verification",
            "recording": "recording_access",
            "monitoring": "monitoring_access",
        }
        step_state_map = {
            "retry_wait": "retry_scheduled",
            "dead_letter": "failed",
        }
        for item in payload["step_results"]:
            allowed = {
                "target_system", "operation", "state", "external_id",
                "external_reference", "evidence_hash", "error_code", "replayed",
                "step_id", "attempt_count", "credential_reference", "retry_at",
            }
            if not isinstance(item, dict) or set(item) - allowed:
                raise ValueError("invalid_step_result")
            target = target_map.get(
                item.get("target_system"), item.get("target_system")
            )
            step = provision_request.step_ids.filtered(
                lambda row: row.target_system == target
            )[:1]
            if not step:
                continue
            step_state = step_state_map.get(item.get("state"), item.get("state"))
            if step_state not in dict(step._fields["state"].selection):
                raise ValueError("invalid_step_state")
            values = {
                "state": step_state,
                "external_id": item.get("external_id"),
                "external_reference": item.get("external_reference"),
                "response_hash": item.get("evidence_hash"),
                "attempt_count": int(item.get("attempt_count") or 0),
                "last_error_code": False,
                "last_error_sanitized": False,
                "completed_at": fields.Datetime.now(),
                "verification_state": (
                    "verified" if step_state == "verified"
                    else "failed" if step_state in ("failed", "blocked") else "pending"
                ),
            }
            if item.get("error_code"):
                values["last_error_code"] = re.sub(
                    r"[^A-Z0-9_.-]", "_", item["error_code"].upper()
                )[:64]
            step.write(values)
        provision_request.state = state
        provision_request._audit(event_type, "accepted", after={
            "state": state,
            "step_evidence": [
                item.get("evidence_hash") for item in payload["step_results"]
                if item.get("evidence_hash")
            ],
        })
        return {"state": "accepted"}

    def action_suspend(self):
        if not self.env.su and not self.env.user.has_group(
            "codestra_identity_provisioning.group_provisioning_approver"
        ):
            raise AccessError("Provisioning approval permission is required.")
        for request in self:
            if request.request_type != "suspend":
                raise UserError("A suspension requires a suspend request.")
            request._dispatch_lifecycle_to_service("suspend")
            links = self.env["codestra.identity.link"].search([
                ("employee_id", "=", request.employee_id.id),
            ])
            links._set_lifecycle_state("suspended")
            request.employee_id.provisioning_state = "suspended"
            request.employment_status = "suspended"
            request.state = "suspended"
            request._audit("identity.suspended", "accepted")

    def action_reactivate(self):
        if not self.env.su and not self.env.user.has_group(
            "codestra_identity_provisioning.group_provisioning_approver"
        ):
            raise AccessError("Provisioning approval permission is required.")
        for request in self:
            if request.request_type != "reactivate":
                raise UserError("Reactivation requires a reactivate request.")
            request._dispatch_lifecycle_to_service("reactivate")
            links = self.env["codestra.identity.link"].search([
                ("employee_id", "=", request.employee_id.id),
            ])
            links._set_lifecycle_state("active")
            request.employee_id.provisioning_state = "active"
            request.employment_status = "active"
            request.state = "active"
            request._audit("identity.reactivated", "accepted")

    def action_terminate(self):
        if not self.env.su and not self.env.user.has_group(
            "codestra_identity_provisioning.group_provisioning_approver"
        ):
            raise AccessError("Provisioning approval permission is required.")
        for request in self:
            if request.request_type != "terminate":
                raise UserError("A termination requires a terminate request.")
            request._dispatch_lifecycle_to_service("terminate")
            request.state = "termination_pending"
            links = self.env["codestra.identity.link"].search([
                ("employee_id", "=", request.employee_id.id),
            ])
            links._set_lifecycle_state("terminated")
            assignments = self.env["codestra.extension.assignment"].search([
                ("employee_id", "=", request.employee_id.id),
                ("state", "in", ("reserved", "committed")),
            ])
            assignments.write({
                "state": "released", "released_at": fields.Datetime.now(),
            })
            request.employee_id.provisioning_state = "terminated"
            request.employment_status = "terminated"
            request.state = "terminated"
            request._audit("identity.terminated", "accepted")

    def _lifecycle_targets(self):
        self.ensure_one()
        targets = []
        if self.needs_keycloak:
            targets.append("keycloak")
        if self.needs_vicidial:
            targets.append("vicidial")
        if self.needs_sip_endpoint:
            targets.append("sip")
        if self.needs_company_email:
            targets.append("email_provider")
        return targets

    def _dispatch_lifecycle_to_service(self, operation):
        self.ensure_one()
        self.assert_safe_mode()
        employee_number = self.employee_id.codestra_employee_number
        if not employee_number:
            raise UserError("The employee identifier has not been reserved.")
        timestamp = datetime.now(timezone.utc).isoformat()
        request_id = "%s-%s" % (self.id, operation)
        correlation = "%s:%s" % (self.correlation_id, operation)
        steps = []
        for sequence, target in enumerate(self._lifecycle_targets(), 1):
            step_key = hashlib.sha256(
                ("%s:%s:%s" % (self.idempotency_key, operation, target)).encode()
            ).hexdigest()
            steps.append({
                "schema_version": "1.0",
                "request_id": request_id,
                "correlation_id": correlation,
                "idempotency_key": step_key,
                "employee_id": employee_number,
                "target_system": target,
                "operation": operation,
                "timestamp": timestamp,
                "step_id": "%s-%s-%s" % (self.id, operation, target),
                "sequence": sequence * 10,
                "max_attempts": 3,
                "payload": {},
            })
        envelope = {
            "schema_version": "1.0",
            "request_id": request_id,
            "correlation_id": correlation,
            "idempotency_key": hashlib.sha256(
                ("%s:%s" % (self.idempotency_key, operation)).encode()
            ).hexdigest(),
            "employee_id": employee_number,
            "target_system": "odoo",
            "operation": operation,
            "timestamp": timestamp,
            "steps": steps,
        }
        return self.env["codestra.private.provisioning.service"].request(
            "POST",
            "/v1/identities/%s/%s" % (
                urllib.parse.quote(employee_number, safe=""),
                operation,
            ),
            envelope,
        )

    def action_reconcile(self):
        if not self.env.su and not self.env.user.has_group(
            "codestra_identity_provisioning.group_provisioning_approver"
        ):
            raise AccessError("Provisioning approval permission is required.")
        for request in self:
            request.assert_safe_mode()
            employee_number = request.employee_id.codestra_employee_number
            if not employee_number:
                raise UserError("The employee identifier has not been reserved.")
            timestamp = datetime.now(timezone.utc).isoformat()
            response = self.env["codestra.private.provisioning.service"].request(
                "GET",
                "/v1/identities/%s/reconciliation" % urllib.parse.quote(
                    employee_number, safe=""
                ),
                {
                    "schema_version": "1.0",
                    "request_id": "%s-reconcile" % request.id,
                    "correlation_id": "%s:reconcile" % request.correlation_id,
                    "idempotency_key": hashlib.sha256(
                        ("%s:reconcile" % request.idempotency_key).encode()
                    ).hexdigest(),
                    "employee_id": employee_number,
                    "target_system": "reconciliation",
                    "operation": "reconcile",
                    "timestamp": timestamp,
                    "payload": {},
                },
            )
            state = response.get("state")
            aligned = state == "aligned"
            now = fields.Datetime.now()
            request.write({
                "drift_state": "aligned" if aligned else "drift_detected",
                "last_reconciled_at": now,
            })
            links = self.env["codestra.identity.link"].search([
                ("employee_id", "=", request.employee_id.id),
            ])
            links.write({
                "drift_state": "aligned" if aligned else "privilege_drift",
                "last_reconciled_at": now,
            })
            request._audit(
                "identity.reconciled",
                "accepted" if aligned else "failed",
                after={"drift_state": request.drift_state},
            )
        return True

    @api.depends("step_ids.state", "step_ids.mandatory", "step_ids.verification_state")
    def _compute_mandatory_steps(self):
        for request in self:
            mandatory = request.step_ids.filtered("mandatory")
            request.mandatory_steps_complete = bool(mandatory) and all(
                step.state in ("verified", "skipped")
                and step.verification_state == "verified"
                for step in mandatory
            )

    @api.onchange("business_unit_id")
    def _onchange_business_unit_id(self):
        """Clear dependent choices that are outside the selected authority scope."""
        for request in self:
            unit = request.business_unit_id
            if request.primary_campaign_id.business_unit_id != unit:
                request.primary_campaign_id = False
                request.campaign_ids = [(5, 0, 0)]
            if request.role_template_id.business_unit_id != unit:
                request.role_template_id = False
            if request.extension_pool_id.business_unit_id != unit:
                request.extension_pool_id = False
            if request.department_id.business_unit_id != unit:
                request.department_id = False
            if request.operational_team_id.business_unit_id != unit:
                request.operational_team_id = False
            if request.supervisor_id and request.supervisor_id not in request.operational_team_id.supervisor_ids:
                request.supervisor_id = False

    @api.onchange("primary_campaign_id")
    def _onchange_primary_campaign_id(self):
        """Use the campaign registry as the reusable source for dependent values."""
        for request in self:
            campaign = request.primary_campaign_id
            if not campaign:
                request.campaign_ids = [(5, 0, 0)]
                continue
            request.business_unit_id = campaign.business_unit_id
            request.branch_id = campaign.branch_id
            request.campaign_ids = [(6, 0, campaign.ids)]
            request.calling_hours_policy_id = (
                campaign.calling_hours_policy_id.display_name
                if campaign.calling_hours_policy_id else False
            )
            teams = campaign.team_ids.filtered("active")
            if len(teams) == 1:
                request.operational_team_id = teams
                request.department_id = teams.department_id
            supervisors = campaign.supervisor_ids & request.operational_team_id.supervisor_ids
            if len(supervisors) == 1:
                request.supervisor_id = supervisors
            pools = request.env["codestra.extension.pool"].search([
                ("business_unit_id", "=", campaign.business_unit_id.id),
                ("active", "=", True),
            ], limit=2)
            if len(pools) == 1:
                request.extension_pool_id = pools

    @api.onchange("operational_team_id")
    def _onchange_operational_team_id(self):
        for request in self:
            team = request.operational_team_id
            if team:
                request.business_unit_id = team.business_unit_id
                request.department_id = team.department_id
            if request.supervisor_id not in team.supervisor_ids:
                request.supervisor_id = False

    @api.model
    def monitoring_snapshot(self, campaign_code=None, limit=200):
        """Return a tenant-scoped, secret-free identity and campaign projection."""
        if not self.env.user.has_group(
            "codestra_identity_provisioning.group_provisioning_user"
        ):
            raise AccessError("Provisioning monitoring permission is required.")
        limit = max(1, min(int(limit or 200), 200))
        domain = [("request_type", "=", "onboard")]
        requests = self.search(domain, order="employee_id, create_date desc", limit=limit)
        if campaign_code:
            # Apply the code match after the tenant-scoped request search.  A
            # dotted relational domain is not portable across the supported
            # Odoo registry variants and can incorrectly return no rows.
            requests = requests.filtered(
                lambda item: item.primary_campaign_id.code == campaign_code
            )
        seen = set()
        agents = []
        for provision in requests:
            employee = provision.employee_id
            if employee.id in seen:
                continue
            seen.add(employee.id)
            links = employee.identity_link_ids
            keycloak = links.filtered(lambda link: link.system == "keycloak" and link.is_primary)[:1]
            vicidial = links.filtered(lambda link: link.system == "vicidial" and link.is_primary)[:1]
            sip = links.filtered(lambda link: link.system == "sip" and link.is_primary)[:1]
            campaigns = provision.campaign_ids or provision.primary_campaign_id
            active = bool(
                provision.state == "active"
                and provision.employment_status == "active"
                and keycloak.state == "active"
                and vicidial.state == "active"
            )
            agents.append({
                "employee_id": employee.codestra_employee_number or str(employee.id),
                "display_name": employee.name,
                "keycloak_username": keycloak.external_username or False,
                "vicidial_username": vicidial.external_username or False,
                "campaigns": [
                    {"id": campaign.id, "code": campaign.code, "name": campaign.name}
                    for campaign in campaigns
                ],
                "role": provision.role_template_id.code,
                "extension": sip.extension or False,
                "provisioning_state": provision.state,
                "employment_status": provision.employment_status,
                "identity_state": keycloak.state or "missing",
                "telephony_state": vicidial.state or "missing",
                "phone_registration_state": sip.state or "missing",
                "is_active": active,
                "last_reconciled_at": fields.Datetime.to_string(
                    provision.last_reconciled_at
                ) if provision.last_reconciled_at else False,
            })
        return {"agents": agents, "count": len(agents)}

    @api.constrains(
        "business_unit_id", "branch_id", "department_id", "operational_team_id",
        "supervisor_id", "primary_campaign_id", "campaign_ids", "inbound_group_ids",
        "role_template_id", "extension_pool_id"
    )
    def _check_scope_and_approvals(self):
        for request in self:
            unit = request.business_unit_id
            if request.branch_id and unit not in request.branch_id.business_unit_ids:
                raise ValidationError("Branch is outside the business unit.")
            if (
                request.employee_id.call_center_branch_id
                and request.branch_id
                and request.employee_id.call_center_branch_id != request.branch_id
            ):
                raise ValidationError("Employee and provisioning-request branches differ.")
            if (
                request.operational_team_id.branch_id
                and request.branch_id
                and request.operational_team_id.branch_id != request.branch_id
            ):
                raise ValidationError("Operational team is outside the branch.")
            if request.department_id.business_unit_id != unit:
                raise ValidationError("Department is outside the business unit.")
            if request.operational_team_id.business_unit_id != unit:
                raise ValidationError("Operational team is outside the business unit.")
            if request.operational_team_id.department_id != request.department_id:
                raise ValidationError("Operational team is outside the department.")
            if request.supervisor_id not in request.operational_team_id.supervisor_ids:
                raise ValidationError("Supervisor is not approved for this team.")
            if (
                request.primary_campaign_id
                and request.primary_campaign_id.business_unit_id != unit
            ):
                raise ValidationError("Primary campaign crosses a business unit.")
            if request.primary_campaign_id and request.campaign_ids != request.primary_campaign_id:
                raise ValidationError("Campaign selection must match the primary campaign.")
            if any(c.business_unit_id != unit for c in request.campaign_ids):
                raise ValidationError("Campaign assignment crosses a business unit.")
            if request.branch_id and any(
                campaign.branch_id and campaign.branch_id != request.branch_id
                for campaign in request.campaign_ids
            ):
                raise ValidationError("Campaign assignment crosses a branch.")
            if any(g.business_unit_id != unit for g in request.inbound_group_ids):
                raise ValidationError("Inbound-group assignment crosses a business unit.")
            if request.role_template_id.business_unit_id != unit:
                raise ValidationError("Role template crosses a business unit.")
            if (
                request.extension_pool_id
                and request.extension_pool_id.business_unit_id != unit
            ):
                raise ValidationError("Extension pool crosses a business unit.")

    def action_submit(self):
        self.filtered(lambda r: r.state != "draft") and (_ for _ in ()).throw(
            UserError("Only draft requests can be submitted.")
        )
        self.write({"state": "pending_approval"})

    def action_approve(self):
        if not self.env.su and not self.env.user.has_group(
            "codestra_identity_provisioning.group_provisioning_approver"
        ):
            raise AccessError("Provisioning approval permission is required.")
        for request in self:
            if request.state != "pending_approval":
                raise UserError("Only pending requests can be approved.")
            template = request.role_template_id
            if not request.operational_approved or not request.it_approved:
                raise UserError("Operational and IT approvals are mandatory.")
            if template.requires_compliance_approval and not request.compliance_approved:
                raise UserError("Compliance approval is mandatory.")
            if template.requires_security_approval and not request.security_approved:
                raise UserError("Security approval is mandatory.")
            conflicts = request.role_template_id.conflicting_template_ids
            if conflicts:
                raise UserError("The role template has unresolved role conflicts.")
            request.state = "approved"

    def action_activate(self):
        if not self.env.su and not self.env.user.has_group(
            "codestra_identity_provisioning.group_provisioning_approver"
        ):
            raise AccessError("Provisioning approval permission is required.")
        for request in self:
            if request.state != "awaiting_user_activation":
                raise UserError("Request is not awaiting user activation.")
            if not request.mandatory_steps_complete:
                raise UserError("Mandatory provisioning steps are not verified.")
            request.state = "active"


class ProvisioningStep(models.Model):
    _name = "codestra.provisioning.step"
    _description = "Idempotent Provisioning Step"
    _order = "request_id, sequence, id"

    request_id = fields.Many2one(
        "codestra.provisioning.request", required=True, ondelete="cascade", index=True
    )
    sequence = fields.Integer(default=10)
    target_system = fields.Selection(
        [("odoo", "Odoo"), ("keycloak", "Keycloak"), ("email", "Email"),
         ("vicidial", "VICIdial"), ("sip", "SIP"),
         ("voicemail", "Voicemail"), ("recording", "Recording"),
         ("monitoring", "Monitoring"),
         ("agent_desktop", "Agent Desktop"),
         ("voicemail", "Voicemail"),
         ("recording_access", "Recording Access"),
         ("monitoring_access", "Monitoring Access"),
         ("secret_store", "Secret Store"), ("verification", "Verification")],
        required=True,
    )
    operation = fields.Char(required=True)
    state = fields.Selection(
        [("pending", "Pending"), ("reserved", "Reserved"),
         ("running", "Running"), ("succeeded", "Succeeded"),
         ("failed", "Failed"), ("blocked", "Blocked"),
         ("retry_scheduled", "Retry Scheduled"),
         ("verification_pending", "Verification Pending"),
         ("verified", "Verified"), ("skipped", "Skipped"),
         ("compensated", "Compensated"), ("cancelled", "Cancelled")],
        default="pending", required=True,
    )
    mandatory = fields.Boolean(default=True)
    idempotency_key = fields.Char(required=True, copy=False, index=True)
    attempt_count = fields.Integer(default=0)
    max_attempts = fields.Integer(default=3)
    retryable = fields.Boolean(default=True)
    next_retry_at = fields.Datetime()
    started_at = fields.Datetime()
    completed_at = fields.Datetime()
    external_id = fields.Char(copy=False)
    external_reference = fields.Char(copy=False)
    credential_reference_id = fields.Many2one(
        "codestra.credential.reference", ondelete="restrict"
    )
    response_hash = fields.Char(copy=False)
    verification_state = fields.Selection(
        [("pending", "Pending"), ("verified", "Verified"),
         ("failed", "Failed"), ("unknown", "Unknown")],
        default="pending", required=True,
    )
    last_error_code = fields.Char(copy=False)
    last_error_sanitized = fields.Text(copy=False)
    compensation_state = fields.Selection(
        [("not_required", "Not Required"), ("pending", "Pending"),
         ("completed", "Completed"), ("failed", "Failed")],
        default="not_required", required=True,
    )

    _step_idempotency_unique = models.Constraint(
        "unique(idempotency_key)", "Provisioning-step idempotency keys must be unique."
    )
    _operation_unique = models.Constraint(
        "unique(request_id, target_system, operation)",
        "Request, system, and operation combinations must be unique.",
    )

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            if not values.get("idempotency_key"):
                raw = "%s:%s:%s" % (
                    values["request_id"], values["target_system"], values["operation"]
                )
                values["idempotency_key"] = hashlib.sha256(raw.encode()).hexdigest()
        return super().create(values_list)

    def mark_failed(self, code, error):
        for step in self:
            step.write({
                "state": "failed",
                "attempt_count": step.attempt_count + 1,
                "last_error_code": re.sub(r"[^A-Z0-9_.-]", "_", code.upper())[:64],
                "last_error_sanitized": sanitized_error(error),
                "completed_at": fields.Datetime.now(),
                "verification_state": "failed",
            })
            step.request_id.state = "partially_provisioned"
            step.request_id._audit("step.failed", "failed", step=step, after={
                "error_code": step.last_error_code,
            })


class ProvisioningAudit(models.Model):
    _name = "codestra.provisioning.audit"
    _description = "Append-Only Provisioning Audit"
    _order = "timestamp desc, id desc"
    _log_access = False

    request_id = fields.Many2one(
        "codestra.provisioning.request", required=True, ondelete="restrict"
    )
    step_id = fields.Many2one("codestra.provisioning.step", ondelete="restrict")
    event_type = fields.Char(required=True, index=True)
    actor_id = fields.Many2one("res.users", ondelete="restrict")
    actor_system = fields.Char(required=True)
    correlation_id = fields.Char(required=True, index=True)
    timestamp = fields.Datetime(default=fields.Datetime.now, required=True)
    sanitized_before = fields.Json()
    sanitized_after = fields.Json()
    result = fields.Char(required=True)
    evidence_hash = fields.Char(required=True)
    source_ip_hash = fields.Char()

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            encoded = json.dumps(
                [values.get("sanitized_before"), values.get("sanitized_after")],
                sort_keys=True, default=str,
            )
            values.setdefault("evidence_hash", hashlib.sha256(encoded.encode()).hexdigest())
        return super().create(values_list)

    def write(self, values):
        raise AccessError("Provisioning audit records are append-only.")

    def unlink(self):
        raise AccessError("Provisioning audit records cannot be deleted.")


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    codestra_employee_number = fields.Char(copy=False, index=True)
    provisioning_state = fields.Selection(
        [("unmanaged", "Unmanaged"), ("pending", "Pending"),
         ("active", "Active"), ("suspended", "Suspended"),
         ("terminated", "Terminated")],
        default="unmanaged", required=True, copy=False,
    )
    identity_link_ids = fields.One2many(
        "codestra.identity.link", "employee_id", groups="hr.group_hr_user"
    )

    _codestra_employee_number_unique = models.Constraint(
        "unique(codestra_employee_number)", "Employee numbers must be unique."
    )


class ResUsers(models.Model):
    _inherit = "res.users"

    codestra_role_template_id = fields.Many2one(
        "codestra.role.template", ondelete="restrict"
    )
    codestra_identity_link_ids = fields.Many2many(
        "codestra.identity.link", compute="_compute_codestra_identity_links"
    )

    def _compute_codestra_identity_links(self):
        for user in self:
            employee = self.env["hr.employee"].search([("user_id", "=", user.id)], limit=1)
            user.codestra_identity_link_ids = employee.identity_link_ids


class ResPartner(models.Model):
    _inherit = "res.partner"

    codestra_recovery_email = fields.Char(
        groups="codestra_identity_provisioning.group_provisioning_approver"
    )
    codestra_recovery_phone = fields.Char(
        groups="codestra_identity_provisioning.group_provisioning_approver"
    )


class BusinessUnitExtension(models.Model):
    _inherit = "call.center.business.unit"

    provisioning_role_template_ids = fields.One2many(
        "codestra.role.template", "business_unit_id"
    )
    extension_pool_ids = fields.One2many(
        "codestra.extension.pool", "business_unit_id"
    )

    @api.model_create_multi
    def create(self, values_list):
        units = super().create(values_list)
        template_model = self.env["codestra.role.template"].sudo().with_context(
            tracking_disable=True, mail_create_nolog=True
        )
        for unit in units:
            for code, policy in DEFAULT_ROLE_POLICIES.items():
                template_model.create({
                    "name": code.replace("_", " ").title(),
                    "code": code,
                    "business_unit_id": unit.id,
                    "company_id": unit.company_id.id,
                    **policy,
                })
        return units


class CampaignExtension(models.Model):
    _inherit = "call.center.campaign"

    provisioning_enabled = fields.Boolean(default=False)


class OperationalTeamExtension(models.Model):
    _inherit = "call.center.team"

    provisioning_approver_ids = fields.Many2many(
        "res.users", "codestra_team_provisioning_approver_rel"
    )
