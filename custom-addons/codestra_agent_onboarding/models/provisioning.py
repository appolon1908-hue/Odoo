import hashlib
import json
import re
import urllib.parse
import uuid

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from odoo.addons.codestra_cc_identity.models.identity import IDENTITY_WRITE_CAPABILITY

from odoo.addons.codestra_identity_provisioning.models.provisioning import (
    normalize_identifier,
)

from .middleware_client import (
    AgentProvisioningOutcomeUnknown,
    AgentProvisioningRejected,
)


OPERATIONAL_ROLES = {"agent", "senior_agent", "supervisor"}
ROLE_GROUP_XMLIDS = {
    "agent": "codestra_cc_security.group_cc_campaign_agent",
    "senior_agent": "codestra_cc_security.group_cc_senior_agent",
    "supervisor": "codestra_cc_security.group_cc_campaign_supervisor",
}
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
IMMUTABLE_ASSIGNMENT_FIELDS = {
    "company_id",
    "integration_uuid",
    "employee_id",
    "campaign_id",
    "campaign_role",
    "branch_id",
    "department_id",
    "operational_team_id",
    "supervisor_id",
    "role_template_id",
    "activation_email",
    "preferred_language",
    "timezone",
    "target_start_date",
    "needs_company_email",
    "needs_sip_endpoint",
    "needs_voicemail",
    "needs_recording_access",
    "needs_monitoring_access",
    "needs_agent_desktop",
    "needs_keycloak",
    "needs_vicidial",
    "webrtc_enabled",
    "sms_enabled",
    "sms_sender",
    "sms_sender_type",
    "sms_countries",
    "incoming_calls_enabled",
    "outgoing_calls_enabled",
}
SYSTEM_LINK_FIELDS = {
    "campaign_membership_id",
    "provisioning_request_id",
    "provisioning_outbox_id",
    "activation_outbox_id",
}
COMMUNICATION_CHANNEL_FIELDS = {
    "needs_company_email",
    "needs_sip_endpoint",
    "webrtc_enabled",
    "sms_enabled",
    "sms_sender",
    "sms_sender_type",
    "sms_countries",
    "incoming_calls_enabled",
    "outgoing_calls_enabled",
}
PROVISION_EVENT = "agent.provisioning.requested.v1"
ACTIVATION_EMAIL_EVENT = "agent.activation-email.requested.v1"
EVENT_SCHEMA_VERSION = "1.0"
ONBOARDING_LINK_CAPABILITY = object()
ONBOARDING_VERSION_CAPABILITY = object()
MIDDLEWARE_READBACK_CAPABILITY = object()
MIDDLEWARE_FIELDS = {
    "middleware_request_id",
    "middleware_correlation_id",
    "middleware_state",
    "middleware_version",
    "middleware_last_sync_at",
    "middleware_last_error_code",
    "middleware_last_error_summary",
    "middleware_channel_status",
    "middleware_payload_hash",
    "keycloak_subject",
}
MIDDLEWARE_STATES = {
    "NOT_STARTED",
    "REQUESTED",
    "VALIDATING",
    "IDENTITY",
    "ENTITLEMENTS",
    "CHANNEL_PROVISIONING",
    "READBACK",
    "EFFECTIVE",
    "PARTIAL",
    "FAILED",
    "RECONCILING",
    "SUSPENDED",
    "REVOKED",
    "UNKNOWN",
}
MIDDLEWARE_STEP_TARGETS = {
    ("keycloak", "create_user"): ("keycloak", "upsert_identity"),
    ("keycloak", "assign_approved_roles"): ("agent_desktop", "assign_roles"),
    ("keycloak", "readback"): ("verification", "verify_all"),
    ("vicidial", "sync_agent"): ("vicidial", "upsert_agent"),
    ("vicidial", "reserve_extension"): ("sip", "upsert_endpoint"),
    ("vicidial", "adopt_extension"): ("sip", "upsert_endpoint"),
    ("vicidial", "provision_phone"): ("sip", "upsert_endpoint"),
    ("vicidial", "provision_webrtc"): ("sip", "upsert_endpoint"),
    ("klyrow", "provision_sender_identity"): ("email", "upsert_mailbox"),
    ("telnexa", "provision_sender_profile"): ("sms", "upsert_sender_profile"),
    ("odoo", "upsert_user"): ("odoo", "upsert_user"),
}


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value):
    encoded = value if isinstance(value, bytes) else str(value).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _credential_free_https_url(value, label):
    parsed = urllib.parse.urlsplit((value or "").strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValidationError(
            _(
                "%(label)s must be a credential-free HTTPS URL without a "
                "query or fragment.",
                label=label,
            )
        )
    return parsed.geturl().rstrip("/")


def _nested_keys(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key).lower()
            yield from _nested_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _nested_keys(nested)


class CodestraAgentOnboardingProvisioning(models.Model):
    _inherit = "codestra.agent.onboarding"

    integration_uuid = fields.Char(
        required=True,
        readonly=True,
        copy=False,
        index=True,
        default=lambda self: str(uuid.uuid4()),
    )
    desired_state_version = fields.Integer(
        required=True,
        readonly=True,
        copy=False,
        default=1,
    )
    campaign_id = fields.Many2one(
        "cc.campaign",
        string="Campaign Workspace",
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    business_unit_id = fields.Many2one(
        "call.center.business.unit",
        related="campaign_id.business_unit_id",
        store=True,
        readonly=True,
        index=True,
    )
    campaign_role = fields.Selection(
        [
            ("agent", "Campaign Agent"),
            ("senior_agent", "Senior Agent / SME"),
            ("supervisor", "Campaign Supervisor"),
        ],
        required=True,
        default="agent",
        tracking=True,
    )
    branch_id = fields.Many2one(
        "call.center.branch",
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    department_id = fields.Many2one(
        "call.center.department",
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    operational_team_id = fields.Many2one(
        "call.center.team",
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    supervisor_id = fields.Many2one(
        "res.users",
        ondelete="restrict",
        index=True,
        tracking=True,
        default=lambda self: self.env.user,
    )
    role_template_id = fields.Many2one(
        "codestra.role.template",
        ondelete="restrict",
        index=True,
        tracking=True,
    )
    activation_email = fields.Char(
        index=True,
        tracking=True,
        copy=False,
        help=(
            "Personal or approved recovery address that receives the one-time "
            "account activation message. A reusable password is never stored or sent."
        ),
    )
    preferred_language = fields.Selection(
        selection=lambda self: self.env["res.lang"].get_installed(),
        default=lambda self: self.env.user.lang,
    )
    timezone = fields.Selection(
        selection=lambda self: self.env["res.users"]
        ._fields["tz"]
        ._description_selection(self.env),
        default=lambda self: self.env.user.tz or "UTC",
    )
    needs_company_email = fields.Boolean(default=True, tracking=True)
    needs_sip_endpoint = fields.Boolean(default=True, tracking=True)
    needs_voicemail = fields.Boolean(default=True, tracking=True)
    needs_recording_access = fields.Boolean(tracking=True)
    needs_monitoring_access = fields.Boolean(tracking=True)
    needs_agent_desktop = fields.Boolean(default=True, tracking=True)
    sms_sender = fields.Char(copy=False, tracking=True)
    sms_sender_type = fields.Char(default="alphanumeric", copy=False)
    sms_countries = fields.Json(default=list, copy=False)
    needs_keycloak = fields.Boolean(default=True, tracking=True)
    needs_vicidial = fields.Boolean(default=True, tracking=True)
    campaign_membership_id = fields.Many2one(
        "cc.campaign.membership",
        ondelete="restrict",
        readonly=True,
        copy=False,
        tracking=True,
    )
    provisioning_outbox_id = fields.Many2one(
        "codestra.runtime.integration.outbox",
        ondelete="restrict",
        readonly=True,
        copy=False,
    )
    activation_outbox_id = fields.Many2one(
        "codestra.runtime.integration.outbox",
        ondelete="restrict",
        readonly=True,
        copy=False,
    )
    access_request_prepared_at = fields.Datetime(readonly=True, copy=False)
    provisioning_started_at = fields.Datetime(readonly=True, copy=False)
    activation_email_requested_at = fields.Datetime(readonly=True, copy=False)
    middleware_request_id = fields.Char(readonly=True, copy=False, index=True, tracking=True)
    middleware_correlation_id = fields.Char(readonly=True, copy=False, index=True)
    middleware_state = fields.Selection(
        [(state, state.replace("_", " ").title()) for state in sorted(MIDDLEWARE_STATES)],
        default="NOT_STARTED",
        required=True,
        readonly=True,
        copy=False,
        index=True,
        tracking=True,
    )
    middleware_version = fields.Integer(default=0, readonly=True, copy=False)
    middleware_last_sync_at = fields.Datetime(readonly=True, copy=False)
    middleware_last_error_code = fields.Char(readonly=True, copy=False)
    middleware_last_error_summary = fields.Text(readonly=True, copy=False)
    middleware_channel_status = fields.Json(default=list, readonly=True, copy=False)
    middleware_payload_hash = fields.Char(size=64, readonly=True, copy=False, index=True)
    keycloak_subject = fields.Char(readonly=True, copy=False, index=True)

    _integration_uuid_unique = models.Constraint(
        "unique(integration_uuid)",
        "Agent-onboarding integration UUIDs must be unique.",
    )
    _desired_state_version_positive = models.Constraint(
        "check(desired_state_version > 0)",
        "Agent-onboarding desired-state versions must be positive.",
    )

    def _require_global_administrator_for_channels(self):
        if self.env.uid != SUPERUSER_ID and not self.env.user.has_group(
            "codestra_cc_security.group_cc_global_administrator"
        ):
            raise AccessError(
                _(
                    "Only a global contact-center administrator may change "
                    "communication channel switches (email, SMS, phone, WebRTC)."
                )
            )

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            if COMMUNICATION_CHANNEL_FIELDS.intersection(values):
                self._require_global_administrator_for_channels()
            values.setdefault("integration_uuid", str(uuid.uuid4()))
            values.setdefault("desired_state_version", 1)
        return super().create(values_list)

    def write(self, values):
        if COMMUNICATION_CHANNEL_FIELDS.intersection(values):
            self._require_global_administrator_for_channels()
        protected = IMMUTABLE_ASSIGNMENT_FIELDS & values.keys()
        if protected:
            for record in self:
                if record.campaign_membership_id or record.provisioning_request_id:
                    raise AccessError(
                        _(
                            "Prepared campaign access is immutable. Use the governed "
                            "revoke-then-grant reassignment workflow."
                        )
                    )
        if (
            MIDDLEWARE_FIELDS.intersection(values)
            and self.env.context.get("_codestra_middleware_readback_capability")
            is not MIDDLEWARE_READBACK_CAPABILITY
        ):
            raise AccessError(_("Middleware read-back fields are system managed."))
        if (
            SYSTEM_LINK_FIELDS.intersection(values)
            and self.env.context.get("_codestra_onboarding_link_capability")
            is not ONBOARDING_LINK_CAPABILITY
        ):
            raise AccessError(_("Onboarding integration links are system managed."))
        if (
            "desired_state_version" in values
            and self.env.context.get("_codestra_onboarding_version_capability")
            is not ONBOARDING_VERSION_CAPABILITY
        ):
            raise AccessError(_("Desired-state versions are system managed."))
        return super().write(values)

    def _write_system_links(self, values):
        return self.with_context(
            _codestra_onboarding_link_capability=ONBOARDING_LINK_CAPABILITY
        ).write(values)

    def _write_middleware(self, values):
        return self.with_context(
            _codestra_middleware_readback_capability=MIDDLEWARE_READBACK_CAPABILITY
        ).write(values)

    @api.onchange("employee_id")
    def _onchange_employee_id(self):
        for record in self:
            if record.employee_id and not record.activation_email:
                record.activation_email = record.employee_id.work_email or ""

    @api.onchange("campaign_id")
    def _onchange_campaign_id(self):
        for record in self:
            campaign = record.campaign_id
            if not campaign:
                continue
            legacy = campaign.legacy_campaign_id
            if len(legacy.team_ids) == 1:
                record.operational_team_id = legacy.team_ids
                record.department_id = legacy.team_ids.department_id
            if len(legacy.supervisor_ids) == 1:
                record.supervisor_id = legacy.supervisor_ids
            if legacy.start_date:
                record.target_start_date = legacy.start_date
            if legacy.timezone:
                record.timezone = legacy.timezone

    @api.constrains(
        "company_id",
        "campaign_id",
        "branch_id",
        "department_id",
        "operational_team_id",
        "supervisor_id",
        "role_template_id",
        "activation_email",
        "needs_vicidial",
        "sms_enabled",
        "sms_sender",
        "sms_sender_type",
        "sms_countries",
    )
    def _check_assignment_scope(self):
        for record in self:
            if record.activation_email and not EMAIL_PATTERN.fullmatch(
                record.activation_email.strip()
            ):
                raise ValidationError(_("The activation email address is invalid."))
            if record.sms_enabled and not (record.sms_sender or "").strip():
                raise ValidationError(_("SMS provisioning requires an approved sender."))
            campaign = record.campaign_id
            if not campaign:
                continue
            legacy = campaign.legacy_campaign_id
            unit = legacy.business_unit_id
            if unit.company_id != record.company_id:
                raise ValidationError(
                    _("The campaign business unit belongs to another company.")
                )
            if record.branch_id and unit not in record.branch_id.business_unit_ids:
                raise ValidationError(
                    _("The branch is outside the campaign business unit.")
                )
            if record.department_id and record.department_id.business_unit_id != unit:
                raise ValidationError(
                    _("The department is outside the campaign business unit.")
                )
            if (
                record.operational_team_id
                and record.operational_team_id.business_unit_id != unit
            ):
                raise ValidationError(
                    _("The operational team is outside the campaign business unit.")
                )
            if (
                record.operational_team_id
                and record.department_id
                and record.operational_team_id.department_id != record.department_id
            ):
                raise ValidationError(
                    _("The operational team is outside the department.")
                )
            if (
                record.operational_team_id
                and record.supervisor_id
                and record.supervisor_id
                not in record.operational_team_id.supervisor_ids
            ):
                raise ValidationError(
                    _("The selected supervisor is not approved for this team.")
                )
            if (
                record.role_template_id
                and record.role_template_id.business_unit_id != unit
            ):
                raise ValidationError(
                    _("The role template is outside the campaign business unit.")
                )
            if (
                legacy.team_ids
                and record.operational_team_id
                and record.operational_team_id not in legacy.team_ids
            ):
                raise ValidationError(
                    _("The operational team is not assigned to the selected campaign.")
                )
            if (
                record.needs_vicidial
                and record.role_template_id
                and not record.role_template_id.vicidial_user_group
            ):
                raise ValidationError(
                    _(
                        "VICIdial provisioning requires an approved user group on "
                        "the selected role template."
                    )
                )

    def _require_global_administrator(self):
        if not self.env.user.has_group(
            "codestra_cc_security.group_cc_global_administrator"
        ):
            raise AccessError(
                _("Only a global contact-center administrator may prepare access.")
            )

    def _assert_assignment_ready(self):
        for record in self:
            record._check_assignment_scope()
            if not record.needs_keycloak:
                raise ValidationError(
                    _("Secure onboarding requires Keycloak before access preparation.")
                )
            if record.role_template_id and not record.role_template_id.active:
                raise ValidationError(_("Select an active role-template version."))
            missing = [
                label
                for value, label in (
                    (record.campaign_id, _("campaign")),
                    (record.department_id, _("department")),
                    (record.operational_team_id, _("operational team")),
                    (record.supervisor_id, _("supervisor")),
                    (record.role_template_id, _("role template")),
                    ((record.activation_email or "").strip(), _("activation email")),
                )
                if not value
            ]
            if missing:
                raise ValidationError(
                    _("Complete the required access fields: %s") % ", ".join(missing)
                )
            if record.campaign_id.lifecycle_state not in {
                "approved",
                "provisioning",
                "provisioned_disabled",
                "testing",
                "staging_ready",
                "activation_pending",
            }:
                raise ValidationError(
                    _("The selected campaign is not approved for agent provisioning.")
                )
            if record.campaign_id.identifier_status != "canonical":
                raise ValidationError(
                    _("Blocked legacy campaign identifiers cannot receive new agents.")
                )
            if not record.campaign_id.is_human_staffed:
                raise ValidationError(
                    _("The selected campaign is not human staffed.")
                )
            if record.role_template_id.conflicting_template_ids:
                raise ValidationError(
                    _("The selected role template has unresolved privilege conflicts.")
                )

    def _generate_unique_login(self, requested_email, Users):
        """Resolve a collision-free login, never attaching to an existing account.

        Tries the requested address first, then ``firstname.lastname@domain``,
        then ``firstname2@domain``, ``firstname3@domain``, ... A collision only
        ever produces a new alternate address; it never causes the new user to
        be attached to the pre-existing account at that login.
        """
        local_part, _sep, domain = requested_email.partition("@")
        name_parts = self.employee_id.name.strip().split()
        firstname = normalize_identifier(name_parts[0]) if name_parts else local_part
        lastname = normalize_identifier(name_parts[-1]) if len(name_parts) > 1 else ""

        def collides(candidate):
            return bool(Users.search([("login", "=ilike", candidate)], limit=1))

        if not collides(requested_email):
            return requested_email
        if lastname:
            candidate = "%s.%s@%s" % (firstname, lastname, domain)
            if not collides(candidate):
                return candidate
        for suffix in range(2, 1000):
            candidate = "%s%s@%s" % (firstname, suffix, domain)
            if not collides(candidate):
                return candidate
        raise ValidationError(_("The email namespace for this identity is exhausted."))

    def _ensure_agent_user(self):
        self.ensure_one()
        employee = self.employee_id.with_user(SUPERUSER_ID)
        unit = self.campaign_id.legacy_campaign_id.business_unit_id
        email = self.activation_email.strip().lower()
        user = employee.user_id.with_user(SUPERUSER_ID)
        Users = self.env["res.users"].with_user(SUPERUSER_ID).with_context(active_test=False)
        if not user:
            email = self._generate_unique_login(email, Users)
            # Archived identities participate in collision lookup, not creation.
            # Odoo synchronizes the new inactive user to its partner and that
            # archive guard must search only active linked users.
            user = Users.with_context(
                active_test=True, no_reset_password=True
            ).create(
                {
                    "name": employee.name,
                    "login": email,
                    "email": email,
                    "active": False,
                    "company_id": self.company_id.id,
                    "company_ids": [(6, 0, self.company_id.ids)],
                    "lang": self.preferred_language or self.env.user.lang,
                    "tz": self.timezone or "UTC",
                    "call_center_business_unit_ids": [(6, 0, unit.ids)],
                    "call_center_default_business_unit_id": unit.id,
                }
            )
            employee.write(
                {
                    "user_id": user.id,
                    "work_email": employee.work_email or email,
                }
            )
        else:
            if user.company_id != self.company_id:
                raise ValidationError(
                    _("The employee user belongs to a different primary company.")
                )
            if user.login.lower() != email:
                raise ValidationError(
                    _(
                        "The employee user login differs from the approved activation "
                        "email. Resolve the identity before provisioning."
                    )
                )
            values = {}
            if unit not in user.call_center_business_unit_ids:
                values["call_center_business_unit_ids"] = [(4, unit.id)]
            if not user.call_center_default_business_unit_id:
                values["call_center_default_business_unit_id"] = unit.id
            if values:
                user.write(values)

        required_group = self.env.ref(ROLE_GROUP_XMLIDS[self.campaign_role])
        operational_groups = self.env["res.groups"].with_user(SUPERUSER_ID).browse(
            [self.env.ref(xmlid).id for xmlid in ROLE_GROUP_XMLIDS.values()]
        )
        group_commands = [
            (3, group.id)
            for group in operational_groups
            if group != required_group and group in user.group_ids
        ]
        if required_group not in user.group_ids:
            group_commands.append((4, required_group.id))
        if group_commands:
            user.write({"group_ids": group_commands})
        return user

    def _ensure_membership(self, user):
        self.ensure_one()
        Membership = self.env["cc.campaign.membership"].with_context(
            active_test=False
        )
        open_memberships = Membership.search(
            [
                ("user_id", "=", user.id),
                ("role", "in", sorted(OPERATIONAL_ROLES)),
                (
                    "state",
                    "in",
                    [
                        "draft",
                        "pending_approval",
                        "pending_sync",
                        "active",
                        "suspended",
                    ],
                ),
            ]
        )
        matching = open_memberships.filtered(
            lambda item: item.campaign_id == self.campaign_id
            and item.role == self.campaign_role
        )
        if len(matching) > 1:
            raise ValidationError(
                _("The agent has duplicate open campaign memberships.")
            )
        conflicting = open_memberships - matching
        if conflicting:
            raise ValidationError(
                _(
                    "The agent already has an open operational assignment. "
                    "Use revoke-then-grant reassignment."
                )
            )
        if matching:
            membership = matching
            if membership.employee_id != self.employee_id:
                raise ValidationError(
                    _("The existing membership belongs to another employee.")
                )
            return membership
        return Membership.create(
            {
                "user_id": user.id,
                "employee_id": self.employee_id.id,
                "campaign_id": self.campaign_id.id,
                "role": self.campaign_role,
                "state": "draft",
                "is_primary_supervisor": self.campaign_role == "supervisor",
                "requested_by_id": self.env.user.id,
                "source_ticket": self.name,
                "vicidial_user_group": (
                    self.role_template_id.vicidial_user_group
                    if self.needs_vicidial
                    else False
                ),
            }
        )

    _CHANNEL_DESIRED_SOURCE_FIELD = {
        "email": "needs_company_email",
        "sms": "sms_enabled",
        "phone": "needs_sip_endpoint",
        "webrtc": "webrtc_enabled",
    }

    def _ensure_agent_channels(self):
        """Create (or resync) the ``codestra.agent.channel`` intent rows for
        this onboarding's employee from its own desired-state fields.

        ``codestra.agent.channel`` (``codestra_identity_provisioning``) is
        the source of truth for per-channel provisioning intent going
        forward; this onboarding record's ``needs_company_email``,
        ``needs_sip_endpoint``, ``webrtc_enabled``, and ``sms_enabled`` stay
        the Super Admin's desired-state *input* fields, projected here onto
        the channel rows rather than onto ``cc.campaign.membership`` booleans
        directly. Idempotent: never duplicates a (employee, channel_type)
        row, and only rewrites ``desired_enabled`` when it actually changed.
        """
        self.ensure_one()
        Channel = self.env["codestra.agent.channel"].with_user(SUPERUSER_ID)
        existing_by_type = {
            channel.channel_type: channel
            for channel in Channel.search([("employee_id", "=", self.employee_id.id)])
        }
        for channel_type, source_field in self._CHANNEL_DESIRED_SOURCE_FIELD.items():
            desired = bool(getattr(self, source_field))
            voice_values = (
                {
                    "incoming_allowed": self.incoming_calls_enabled,
                    "outgoing_allowed": self.outgoing_calls_enabled,
                }
                if channel_type in ("phone", "webrtc")
                else {}
            )
            channel = existing_by_type.get(channel_type)
            if channel:
                changes = {
                    key: value
                    for key, value in {"desired_enabled": desired, **voice_values}.items()
                    if channel[key] != value
                }
                if changes:
                    channel.write(changes)
            else:
                Channel.create(
                    {
                        "employee_id": self.employee_id.id,
                        "membership_id": self.campaign_membership_id.id,
                        "provisioning_request_id": self.provisioning_request_id.id or False,
                        "channel_type": channel_type,
                        "desired_enabled": desired,
                        **voice_values,
                    }
                )

    def _provisioning_idempotency_key(self):
        self.ensure_one()
        # ``action_prepare_access`` has already required the global contact-center
        # administrator role and validated this exact campaign assignment.  Read
        # the immutable canonical identifier in that governed system context so
        # a caller does not need a circular pre-existing campaign membership in
        # order to create their first membership request.
        campaign_workspace_uuid = self.with_user(
            SUPERUSER_ID
        ).campaign_id.workspace_uuid
        return _sha256(
            "|".join(
                (
                    "agent-onboarding-v1",
                    self.integration_uuid,
                    str(self.employee_id.id),
                    campaign_workspace_uuid,
                    self.campaign_role,
                    fields.Date.to_string(self.target_start_date),
                )
            )
        )

    def _ensure_provisioning_request(self, user, membership):
        self.ensure_one()
        key = self._provisioning_idempotency_key()
        Request = self.env["codestra.provisioning.request"].with_context(
            active_test=False
        )
        existing = Request.search([("idempotency_key", "=", key)], limit=1)
        if existing:
            if (
                existing.employee_id != self.employee_id
                or existing.cc_membership_id != membership
                or existing.needs_sms != self.sms_enabled
                or self.with_user(SUPERUSER_ID).campaign_id.legacy_campaign_id
                not in existing.with_user(SUPERUSER_ID).campaign_ids
            ):
                raise ValidationError(
                    _("The provisioning idempotency key is already bound.")
                )
            return existing
        # Creation is a governed system transition reached only through
        # ``action_prepare_access`` after global-admin and assignment checks.
        # The system-user scope is limited to materializing this disabled
        # request so the first campaign membership does not depend on already
        # having one.
        return Request.with_user(SUPERUSER_ID).create(
            {
                "request_type": "onboard",
                "employee_id": self.employee_id.id,
                "personal_email": self.activation_email.strip().lower(),
                "requested_for": user.id,
                "supervisor_id": self.supervisor_id.id,
                "company_id": self.company_id.id,
                "business_unit_id": self.business_unit_id.id,
                "branch_id": self.branch_id.id or False,
                "department_id": self.department_id.id,
                "operational_team_id": self.operational_team_id.id,
                "role_template_id": self.role_template_id.id,
                "campaign_ids": [
                    (
                        6,
                        0,
                        self.with_user(SUPERUSER_ID)
                        .campaign_id.legacy_campaign_id.ids,
                    )
                ],
                "start_date": self.target_start_date,
                "preferred_language": self.preferred_language,
                "timezone": self.timezone or "UTC",
                "needs_company_email": self.needs_company_email,
                "needs_sip_endpoint": self.needs_sip_endpoint,
                "needs_voicemail": self.needs_voicemail,
                "needs_recording_access": self.needs_recording_access,
                "needs_monitoring_access": self.needs_monitoring_access,
                "needs_agent_desktop": self.needs_agent_desktop,
                "needs_sms": self.sms_enabled,
                "sms_sender": self.sms_sender.strip() if self.sms_sender else False,
                "needs_keycloak": self.needs_keycloak,
                "needs_vicidial": self.needs_vicidial,
                "idempotency_key": key,
                "cc_membership_id": membership.id,
            }
        ).with_user(self.env.user)

    def _event_context(self):
        self.ensure_one()
        employee = self.with_user(SUPERUSER_ID).employee_id
        campaign = self.with_user(SUPERUSER_ID).campaign_id
        return {
            "onboarding_uuid": self.integration_uuid,
            "onboarding_number": self.name,
            "desired_state_version": self.desired_state_version,
            "provisioning_request_id": self.provisioning_request_id.id,
            "provisioning_request_number": (
                self.provisioning_request_id.request_number
            ),
            "membership_uuid": self.campaign_membership_id.identity_uuid,
            "employee_id": employee.codestra_employee_number,
            "odoo_user_id": employee.user_id.id,
            "login_identifier": employee.user_id.login,
            "business_unit_code": self.business_unit_id.code,
            "campaign_code": campaign.code,
            "campaign_workspace_uuid": campaign.workspace_uuid,
            "campaign_scope_version": campaign.scope_version,
            "role": self.campaign_role,
            "role_template": {
                "code": self.role_template_id.code,
                "version": self.role_template_id.version,
            },
        }

    def _create_integration_event(self, event_type, payload, idempotency_key):
        self.ensure_one()
        return self.env["codestra.runtime.integration.outbox"].create_event(
            event_type=event_type,
            aggregate=self,
            payload=payload,
            correlation_id=self.provisioning_request_id.correlation_id,
            idempotency_key=idempotency_key,
            schema_version=EVENT_SCHEMA_VERSION,
            aggregate_version=self.desired_state_version,
            environment=self.campaign_id.environment,
            campaign=self.campaign_id.legacy_campaign_id,
        )

    def action_submit(self):
        self._assert_assignment_ready()
        return super().action_submit()

    def action_prepare_access(self):
        self._require_state("approved")
        self._require_global_administrator()
        for record in self:
            if record.provisioning_request_id and record.campaign_membership_id:
                continue
            record._assert_assignment_ready()
            user = record._ensure_agent_user()
            membership = record._ensure_membership(user)
            provision_request = record._ensure_provisioning_request(
                user, membership
            )
            if membership.state == "draft":
                membership.action_submit_identity()
            if provision_request.state == "draft":
                provision_request.action_submit()
            record._write_system_links(
                {
                    "campaign_membership_id": membership.id,
                    "provisioning_request_id": provision_request.id,
                    "access_request_prepared_at": fields.Datetime.now(),
                }
            )
            record._ensure_agent_channels()
        return True

    def _sync_reserved_identifiers_to_membership(self):
        self.ensure_one()
        membership = self.campaign_membership_id
        request_record = self.provisioning_request_id
        reservations = self.env["codestra.identifier.reservation"].search(
            [
                ("request_id", "=", request_record.id),
                ("state", "in", ["reserved", "committed"]),
            ]
        )
        by_type = {
            item.identifier_type: item.normalized_value for item in reservations
        }
        values = {}
        if self.needs_vicidial:
            username = by_type.get("vicidial_username")
            if not username:
                raise ValidationError(
                    _("The VICIdial username was not reserved.")
                )
            values["vicidial_user"] = username
            values["vicidial_user_group"] = (
                self.role_template_id.vicidial_user_group
            )
        if self.needs_sip_endpoint:
            assignment = self.env["codestra.extension.assignment"].search(
                [
                    ("request_id", "=", request_record.id),
                    ("state", "in", ["reserved", "committed"]),
                ],
                limit=1,
            )
            if not assignment:
                raise ValidationError(
                    _("The SIP extension was not reserved.")
                )
            values["extension"] = assignment.extension
        if values:
            membership.write(values)

    def _middleware_tenant_id(self):
        self.ensure_one()
        tenant = self.env["ir.config_parameter"].with_user(SUPERUSER_ID).get_param(
            "codestra.middleware.tenant_id"
        )
        if not tenant:
            raise ValidationError(
                _("The Middleware tenant identity is not configured.")
            )
        return tenant.strip()

    def _middleware_supervisor_subject(self):
        self.ensure_one()
        supervisor = self.supervisor_id.with_user(SUPERUSER_ID)
        if "keycloak_subject" in supervisor._fields and supervisor.keycloak_subject:
            return supervisor.keycloak_subject
        membership = self.env["cc.campaign.membership"].with_user(SUPERUSER_ID).search(
            [
                ("user_id", "=", supervisor.id),
                ("campaign_id", "=", self.campaign_id.id),
                ("role", "=", "supervisor"),
                ("state", "in", ["pending_sync", "active", "suspended"]),
            ],
            order="id desc",
            limit=1,
        )
        return membership.keycloak_subject or False

    def _middleware_existing_extension(self):
        self.ensure_one()
        links = self.env["codestra.identity.link"].with_user(SUPERUSER_ID).search(
            [
                ("employee_id", "=", self.employee_id.id),
                ("system", "=", "sip"),
                ("state", "in", ["pending", "active", "suspended"]),
                ("is_primary", "=", True),
            ],
            order="created_at desc, id desc",
            limit=1,
        )
        return links.extension or False

    def _middleware_provisioning_payload(self):
        """Translate the reviewed Odoo assignment into Middleware's one command."""
        self.ensure_one()
        record = self.with_user(SUPERUSER_ID)
        employee = record.employee_id
        employee_number = (employee.codestra_employee_number or "").strip()
        if not employee_number:
            raise ValidationError(
                _("Reserve the employee identifier before starting Middleware provisioning.")
            )
        request_record = record.provisioning_request_id
        membership = record.campaign_membership_id
        campaign = record.campaign_id
        legacy = campaign.legacy_campaign_id
        campaign_id = (legacy.vicidial_campaign_id or campaign.code or "").strip()
        if not campaign_id:
            raise ValidationError(_("The approved campaign has no Middleware identifier."))
        parts = (employee.name or "").strip().split()
        first_name = parts[0] if parts else ""
        last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
        channels = {
            "odoo": True,
            "phone": bool(record.needs_sip_endpoint),
            "webrtc": bool(record.webrtc_enabled),
            "sms": bool(record.sms_enabled),
            "email": bool(record.needs_company_email),
        }
        return {
            "request_id": record.integration_uuid,
            "tenant_id": record._middleware_tenant_id(),
            "employee_id": employee_number,
            "identity": {
                "email": record.activation_email.strip().lower(),
                "first_name": first_name,
                "last_name": last_name,
            },
            "campaigns": [
                {
                    "campaign_id": campaign_id,
                    "role": record.campaign_role,
                    "vicidial_user_id": membership.vicidial_user or None,
                    "vicidial_user_group": membership.vicidial_user_group or None,
                    "vicidial_supervisor_subject": record._middleware_supervisor_subject()
                    or None,
                    "campaign_email": (
                        record.activation_email.strip().lower()
                        if record.needs_company_email
                        else None
                    ),
                    "sms_sender": record.sms_sender.strip() if record.sms_sender else None,
                    "sms_sender_type": record.sms_sender_type or "alphanumeric",
                    "sms_countries": list(record.sms_countries or []),
                }
            ],
            "channels": channels,
            "telephony": {
                "existing_extension": record._middleware_existing_extension() or None,
                "incoming_allowed": True,
                "outgoing_allowed": True,
                "max_webrtc_sessions": 1,
                "extension_pool": (
                    request_record.extension_pool_id.code
                    if request_record.extension_pool_id
                    else legacy.extension_pool
                ),
            },
        }

    @staticmethod
    def _middleware_safe_error(value):
        value = re.sub(
            r"(?i)\b(password|token|secret|credential|authorization)\s*[:=]\s*[^\s,;]+",
            r"\1=[REDACTED]",
            str(value or ""),
        )
        return value[:500]

    @staticmethod
    def _middleware_step_state(value):
        state = str(value or "").lower()
        if state == "succeeded":
            return "verified", "verified"
        if state == "skipped":
            return "skipped", "verified"
        if state == "failed":
            return "failed", "failed"
        if state == "blocked":
            return "blocked", "failed"
        if state in {"retry", "retry_wait", "retry_scheduled"}:
            return "retry_scheduled", "pending"
        if state in {"running", "pending", "reserved"}:
            return "running", "pending"
        return "pending", "pending"

    @staticmethod
    def _middleware_channel_status_from_steps(steps):
        channel_by_step = {
            ("odoo", "upsert_user"): "odoo",
            ("keycloak", "upsert_identity"): "keycloak",
            ("email", "upsert_mailbox"): "email",
            ("klyrow", "provision_sender_identity"): "email",
            ("sms", "upsert_sender_profile"): "sms",
            ("telnexa", "provision_sender_profile"): "sms",
            ("vicidial", "upsert_agent"): "phone",
            ("vicidial", "sync_agent"): "phone",
            ("sip", "upsert_endpoint"): "phone",
            ("vicidial", "provision_webrtc"): "webrtc",
            ("agent_desktop", "assign_roles"): "agent_desktop",
        }
        rows = []
        for item in steps:
            channel = channel_by_step.get((item["system"], item["operation"]))
            if not channel:
                continue
            state = str(item["state"] or "").lower()
            rows.append(
                {
                    "channel": channel,
                    "desired_enabled": True,
                    "requested_state": "requested",
                    "provisioned_state": state or "pending",
                    "effective_access": state in {"succeeded", "verified"},
                    "provider": item["system"],
                    "provider_reference": item["external_reference"] or False,
                    "last_error_code": item["error_code"] or False,
                    "last_error_summary": item["error_summary"] or False,
                    "last_verified_at": item.get("completed_at") or False,
                }
            )
        return rows

    @classmethod
    def _middleware_normalized_result(cls, payload):
        steps = payload.get("steps")
        if steps is None:
            steps = payload.get("step_results")
        if not isinstance(steps, list):
            raise ValueError("invalid_middleware_steps")
        normalized_steps = []
        for item in steps:
            if not isinstance(item, dict):
                raise ValueError("invalid_middleware_step")
            normalized_steps.append(
                {
                    "system": item.get("system") or item.get("target_system"),
                    "operation": item.get("operation"),
                    "state": item.get("state"),
                    "external_reference": item.get("external_reference")
                    or item.get("external_id"),
                    "error_code": item.get("error_code"),
                    "error_summary": item.get("error_summary"),
                    "attempt": item.get("attempt") or item.get("attempt_count") or 1,
                    "readback_state": item.get("readback_state"),
                }
            )
        channels = payload.get("channels")
        if channels is None:
            channels = cls._middleware_channel_status_from_steps(normalized_steps)
        if not isinstance(channels, list):
            raise ValueError("invalid_middleware_channels")
        return {
            "middleware_request_id": str(payload.get("middleware_request_id") or ""),
            "request_id": str(payload.get("request_id") or ""),
            "tenant_id": str(payload.get("tenant_id") or ""),
            "employee_id": str(payload.get("employee_id") or ""),
            "correlation_id": str(payload.get("correlation_id") or ""),
            "state": str(payload.get("state") or ""),
            "version": payload.get("version"),
            "keycloak_subject": payload.get("keycloak_subject") or False,
            "last_error_code": payload.get("last_error_code") or False,
            "last_error_summary": payload.get("last_error_summary") or False,
            "channels": channels,
            "odoo": payload.get("odoo") or {},
            "steps": normalized_steps,
        }

    @classmethod
    def _middleware_result_hash(cls, payload):
        return _sha256(_canonical_json(cls._middleware_normalized_result(payload)))

    def _apply_middleware_result(self, payload, *, authenticated_tenant=None):
        """Apply a terminal/observed Middleware version exactly once."""
        self.ensure_one()
        normalized = self._middleware_normalized_result(payload)
        if normalized["request_id"] != self.integration_uuid:
            raise ValueError("middleware_request_binding_mismatch")
        if authenticated_tenant and normalized["tenant_id"] != authenticated_tenant:
            raise ValueError("middleware_tenant_mismatch")
        if normalized["tenant_id"] != self._middleware_tenant_id():
            raise ValueError("middleware_tenant_mismatch")
        request_record = self.provisioning_request_id
        if not request_record or not self.campaign_membership_id:
            raise ValueError("middleware_odoo_record_incomplete")
        binding = normalized["odoo"]
        if not isinstance(binding, dict):
            raise ValueError("invalid_middleware_odoo_binding")
        if binding and (
            binding.get("onboarding_uuid") != self.integration_uuid
            or str(binding.get("provisioning_request_id")) != str(request_record.id)
            or binding.get("membership_uuid")
            != self.campaign_membership_id.identity_uuid
            or binding.get("desired_state_version") != self.desired_state_version
        ):
            raise ValueError("middleware_odoo_binding_mismatch")
        if (
            normalized["employee_id"]
            and normalized["employee_id"]
            != (self.employee_id.codestra_employee_number or "")
        ):
            raise ValueError("middleware_employee_binding_mismatch")
        if (
            normalized["correlation_id"]
            != request_record.correlation_id
        ):
            raise ValueError("middleware_correlation_mismatch")
        if normalized["state"] not in {
            "EFFECTIVE", "PARTIAL", "FAILED", "SUSPENDED", "REVOKED"
        }:
            raise ValueError("invalid_middleware_state")
        try:
            version = int(normalized["version"])
        except (TypeError, ValueError) as error:
            raise ValueError("invalid_middleware_version") from error
        if version < 1:
            raise ValueError("invalid_middleware_version")
        middleware_id = normalized["middleware_request_id"]
        if not middleware_id or len(middleware_id) > 128:
            raise ValueError("invalid_middleware_request_id")
        result_hash = self._middleware_result_hash(payload)
        if version < self.middleware_version:
            return {
                "state": "stale",
                "middleware_state": self.middleware_state,
                "middleware_version": self.middleware_version,
            }
        if version == self.middleware_version and self.middleware_payload_hash:
            if self.middleware_payload_hash != result_hash:
                raise ValueError("middleware_version_conflict")
            return {
                "state": "replayed",
                "middleware_state": self.middleware_state,
                "middleware_version": self.middleware_version,
            }

        step_rows = request_record.step_ids.with_user(SUPERUSER_ID)
        for item in normalized["steps"]:
            target = MIDDLEWARE_STEP_TARGETS.get(
                (item["system"], item["operation"])
            )
            if not target:
                continue
            target_system, target_operation = target
            step = step_rows.filtered(
                lambda row: row.target_system == target_system
                and row.operation == target_operation
            )[:1]
            if not step:
                continue
            step_state, verification_state = self._middleware_step_state(item["state"])
            try:
                attempt_count = max(1, int(item["attempt"] or 1))
            except (TypeError, ValueError):
                attempt_count = 1
            error_code = re.sub(
                r"[^A-Z0-9_.-]", "_", str(item["error_code"] or "").upper()
            )[:64]
            values = {
                "state": step_state,
                "attempt_count": max(step.attempt_count, attempt_count),
                "external_reference": item["external_reference"] or False,
                "response_hash": _sha256(_canonical_json(item)),
                "last_error_code": error_code or False,
                "last_error_sanitized": (
                    self._middleware_safe_error(item["error_summary"])
                    if item["error_summary"]
                    else False
                ),
                "verification_state": verification_state,
                "completed_at": fields.Datetime.now()
                if str(item["state"] or "").lower()
                in {"succeeded", "failed", "blocked", "skipped"}
                else False,
            }
            step.write(values)

        state = normalized["state"]
        if state == "EFFECTIVE":
            request_state = (
                "awaiting_user_activation"
                if request_record.mandatory_steps_complete
                else "verification"
            )
        elif state == "PARTIAL":
            request_state = "partially_provisioned"
        elif state == "FAILED":
            request_state = "failed"
        elif state == "SUSPENDED":
            request_state = "suspended"
        elif state == "REVOKED":
            request_state = "terminated"
        else:
            request_state = "provisioning"
        request_record.with_user(SUPERUSER_ID).write(
            {
                "state": request_state,
                "last_error_code": (
                    re.sub(
                        r"[^A-Z0-9_.-]", "_", str(normalized["last_error_code"] or "").upper()
                    )[:64]
                    or False
                ),
                "last_error_sanitized": (
                    self._middleware_safe_error(normalized["last_error_summary"])
                    if normalized["last_error_summary"]
                    else False
                ),
            }
        )

        channel_status = []
        for item in normalized["channels"]:
            if not isinstance(item, dict):
                continue
            channel_status.append(
                {
                    "channel": str(item.get("channel") or "")[:32],
                    "desired_enabled": bool(item.get("desired_enabled")),
                    "requested_state": str(item.get("requested_state") or "")[:64]
                    or False,
                    "provisioned_state": str(item.get("provisioned_state") or "")[:64]
                    or False,
                    "effective_access": bool(item.get("effective_access")),
                    "provider": str(item.get("provider") or "")[:32] or False,
                    "provider_reference": str(item.get("provider_reference") or "")[:255]
                    or False,
                    "last_error_code": str(item.get("last_error_code") or "")[:64] or False,
                    "last_error_summary": self._middleware_safe_error(
                        item.get("last_error_summary")
                    )
                    if item.get("last_error_summary")
                    else False,
                    "last_verified_at": item.get("last_verified_at") or False,
                }
            )

        membership = self.campaign_membership_id
        membership_values = {}
        if normalized["keycloak_subject"]:
            membership_values["keycloak_subject"] = str(normalized["keycloak_subject"])[:64]
        email_status = next(
            (item for item in channel_status if item["channel"] == "email"), None
        )
        if email_status and email_status["effective_access"]:
            membership_values["campaign_email_identity"] = (
                email_status["provider_reference"] or False
            )
        membership_values["last_sync_status"] = (
            "matched"
            if state == "EFFECTIVE"
            else "failed"
            if state == "FAILED"
            else "mismatch"
            if state == "PARTIAL"
            else "pending"
        )
        membership_values["read_back_evidence"] = (
            "middleware:%s#%s" % (middleware_id, result_hash)
        )
        membership.with_user(SUPERUSER_ID).with_context(
            _cc_identity_write_capability=IDENTITY_WRITE_CAPABILITY,
            cc_membership_transition=True,
        ).write(membership_values)

        if state == "FAILED":
            self._write_system_links(
                {
                    "state": "failed",
                    "failure_reason": self._middleware_safe_error(
                        normalized["last_error_summary"] or "Middleware provisioning failed."
                    ),
                }
            )
        else:
            self._write_system_links(
                {"state": "provisioning", "failure_reason": False}
            )
        self._write_middleware(
            {
                "middleware_request_id": middleware_id,
                "middleware_correlation_id": normalized["correlation_id"],
                "middleware_state": state,
                "middleware_version": version,
                "middleware_last_sync_at": fields.Datetime.now(),
                "middleware_last_error_code": normalized["last_error_code"] or False,
                "middleware_last_error_summary": (
                    self._middleware_safe_error(normalized["last_error_summary"])
                    if normalized["last_error_summary"]
                    else False
                ),
                "middleware_channel_status": channel_status,
                "middleware_payload_hash": result_hash,
                "keycloak_subject": normalized["keycloak_subject"] or False,
            }
        )
        request_record._audit(
            "middleware.agent_provisioning.readback",
            "accepted",
            after={
                "middleware_request_id": middleware_id,
                "middleware_state": state,
                "middleware_version": version,
                "channel_count": len(channel_status),
            },
        )
        return {
            "state": "accepted",
            "middleware_state": state,
            "middleware_request_id": middleware_id,
            "middleware_version": version,
        }

    def _provisioning_event_payload(self):
        self.ensure_one()
        targets = ["odoo"]
        if self.needs_keycloak:
            targets.append("keycloak")
        if self.needs_company_email:
            targets.append("email_provider")
        if self.needs_vicidial:
            targets.append("vicidial")
        if self.needs_sip_endpoint:
            targets.append("sip")
        if self.needs_agent_desktop:
            targets.append("agent_desktop")
        if self.needs_voicemail:
            targets.append("voicemail")
        if self.needs_recording_access:
            targets.append("recording_access")
        if self.needs_monitoring_access:
            targets.append("monitoring_access")
        if self.webrtc_enabled:
            targets.append("webrtc")
        if self.sms_enabled:
            targets.append("sms")
        return {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_type": PROVISION_EVENT,
            **self._event_context(),
            "recipient_email": self.activation_email.strip().lower(),
            "targets": targets,
            "telephony_assignment": {
                "extension": self.campaign_membership_id.extension or None,
                "webrtc_enabled": self.webrtc_enabled,
                "sms_enabled": self.sms_enabled,
                "webrtc_max_devices": 1,
            },
            "controls": {
                "create_disabled": True,
                "activate_immediately": False,
                "send_activation_email": False,
                "plaintext_password_allowed": False,
                "browser_campaign_selection_allowed": False,
                "change_agent_campaign": False,
                "production_dialing": False,
                "live_call_control": False,
                "webrtc_credential_issuance": False,
            },
        }

    def action_start_provisioning(self):
        self._require_state("approved", "provisioning", "failed")
        self._require_global_administrator()
        for record in self:
            if record.middleware_state == "EFFECTIVE":
                continue
            if (
                not record.provisioning_request_id
                or not record.campaign_membership_id
            ):
                raise ValidationError(
                    _("Prepare the governed access request first.")
                )
            request_record = record.provisioning_request_id
            membership = record.campaign_membership_id
            if request_record.requested_by == self.env.user:
                raise AccessError(
                    _(
                        "The access requester cannot approve the same "
                        "provisioning request."
                    )
                )
            if membership.requested_by_id == self.env.user:
                raise AccessError(
                    _(
                        "The membership requester cannot approve the same "
                        "assignment."
                    )
                )
            if request_record.state == "pending_approval":
                request_record.action_approve()
            if request_record.state == "approved":
                # Reservation and step rows are internal orchestration records whose
                # ACLs are intentionally service-only. The caller has already passed
                # both the global-admin and provisioning-approval gates above.
                request_record.with_user(SUPERUSER_ID).action_reserve_identifiers()
            if request_record.state not in {
                "provisioning",
                "partially_provisioned",
                "verification",
                "awaiting_user_activation",
                "failed",
            }:
                raise ValidationError(
                    _("The provisioning request must be approved and prepared.")
                )
            if membership.state == "pending_approval":
                record._sync_reserved_identifiers_to_membership()
                membership.action_approve_identity()
            if membership.state != "pending_sync":
                raise ValidationError(
                    _(
                        "The campaign membership must be approved and pending "
                        "synchronization."
                    )
                )
            record._write_system_links(
                {
                    "state": "provisioning",
                    "provisioning_started_at": fields.Datetime.now(),
                }
            )
            client = self.env[
                "codestra.agent.provisioning.middleware.client"
            ].with_user(SUPERUSER_ID)
            try:
                if record.middleware_request_id:
                    response = client.reconcile_request(
                        record.middleware_request_id,
                        correlation_id=request_record.correlation_id,
                        reason="Odoo administrator requested provisioning reconciliation.",
                        expected_request_id=record.integration_uuid,
                    )
                else:
                    response = client.create_request(
                        record._middleware_provisioning_payload(),
                        idempotency_key=record._provisioning_idempotency_key(),
                        correlation_id=request_record.correlation_id,
                    )
            except AgentProvisioningOutcomeUnknown as error:
                record._write_middleware(
                    {
                        "middleware_state": "RECONCILING",
                        "middleware_last_sync_at": fields.Datetime.now(),
                        "middleware_last_error_code": "OUTCOME_UNKNOWN",
                        "middleware_last_error_summary": str(error),
                    }
                )
                continue
            except AgentProvisioningRejected:
                raise
            record._apply_middleware_result(response)
        return True

    def _activation_email_payload(self):
        self.ensure_one()
        parameters = self.env["ir.config_parameter"].with_user(SUPERUSER_ID)
        login_url = _credential_free_https_url(
            parameters.get_param("codestra.agent.activation.login_url"),
            _("Agent login URL"),
        )
        try:
            ttl_minutes = int(
                parameters.get_param(
                    "codestra.agent.activation.ttl_minutes", "30"
                )
            )
        except (TypeError, ValueError) as error:
            raise ValidationError(
                _("The activation TTL configuration is invalid.")
            ) from error
        if not 5 <= ttl_minutes <= 1440:
            raise ValidationError(
                _(
                    "The activation email TTL must be between 5 and 1440 "
                    "minutes."
                )
            )
        return {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_type": ACTIVATION_EMAIL_EVENT,
            **self._event_context(),
            "delivery": {
                "channel": "email",
                "provider": "klyrow",
                "mode": "keycloak_execute_actions_email",
                "template_key": "agent-welcome-v1",
                "recipient": self.activation_email.strip().lower(),
                "preferred_language": self.preferred_language or "en_US",
            },
            "login": {
                "identifier": self.employee_id.user_id.login,
                "url": login_url,
                "required_actions": ["UPDATE_PASSWORD", "CONFIGURE_TOTP"],
                "expires_in_minutes": ttl_minutes,
            },
            "controls": {
                "one_time_action_required": True,
                "plaintext_password_allowed": False,
                "link_persistence_allowed": False,
                "activate_immediately": False,
                "production_dialing": False,
            },
        }

    def action_request_activation_email(self):
        self._require_state("provisioning")
        self._require_global_administrator()
        for record in self:
            if not record.needs_keycloak:
                raise ValidationError(
                    _("Secure activation email requires a provisioned Keycloak identity.")
                )
            if record.activation_outbox_id:
                continue
            request_record = record.provisioning_request_id
            membership = record.campaign_membership_id
            if (
                not request_record
                or request_record.state
                not in {"awaiting_user_activation", "active"}
                or not request_record.mandatory_steps_complete
            ):
                raise ValidationError(
                    _(
                        "Secure login email requires every mandatory "
                        "provisioning step to be verified."
                    )
                )
            if (
                not membership
                or membership.state not in {"pending_sync", "active"}
                or membership.last_sync_status != "matched"
                or not membership.read_back_evidence
            ):
                raise ValidationError(
                    _(
                        "Secure login email requires matched campaign identity "
                        "read-back."
                    )
                )
            payload = record._activation_email_payload()
            forbidden = {
                "password",
                "temporary_password",
                "token",
                "secret",
                "private_key",
                "recovery_code",
                "activation_link",
                "action_link",
                "reset_link",
            }
            if forbidden.intersection(_nested_keys(payload)):
                raise ValidationError(
                    _(
                        "Activation email events cannot contain credentials or "
                        "action links."
                    )
                )
            event = record._create_integration_event(
                ACTIVATION_EMAIL_EVENT,
                payload,
                _sha256(
                    "%s|%s|%s"
                    % (
                        record.integration_uuid,
                        record.desired_state_version,
                        ACTIVATION_EMAIL_EVENT,
                    )
                ),
            )
            record._write_system_links(
                {
                    "activation_outbox_id": event.id,
                    "activation_email_requested_at": fields.Datetime.now(),
                }
            )
        return True

    def _successful_activation_results(self):
        self.ensure_one()
        return self.activation_outbox_id.result_inbox_ids.filtered(
            lambda result: result.outcome_explicit
            and result.execution_status == "SUCCEEDED"
            and result.reconciliation_status == "RECONCILED"
            and result.processing_status == "PROCESSED"
        )

    def action_activate(self):
        self._require_state("provisioning")
        for record in self:
            request_record = record.provisioning_request_id
            membership = record.campaign_membership_id
            activation_event = record.activation_outbox_id
            if not request_record or request_record.state != "active":
                raise ValidationError(
                    _(
                        "Activation requires an active and reconciled "
                        "provisioning request."
                    )
                )
            if not membership or membership.state != "active":
                raise ValidationError(
                    _("Activation requires an active campaign membership.")
                )
            if (
                not activation_event
                or activation_event.delivery_state != "delivered"
                or activation_event.integration_status != "COMPLETED"
            ):
                raise ValidationError(
                    _(
                        "Activation requires completed secure-login email "
                        "evidence."
                    )
                )
            successful_results = record._successful_activation_results()
            if not successful_results:
                raise ValidationError(
                    _(
                        "Activation requires a successful and reconciled "
                        "secure-login email result."
                    )
                )
            user = record.employee_id.user_id
            if not user:
                raise ValidationError(_("The employee has no Odoo user."))
            if not user.active:
                user.write({"active": True})
            legacy_campaign = record.campaign_id.legacy_campaign_id
            if record.campaign_role == "supervisor":
                if user not in legacy_campaign.supervisor_ids:
                    legacy_campaign.write(
                        {"supervisor_ids": [(4, user.id)]}
                    )
                if user not in record.operational_team_id.supervisor_ids:
                    record.operational_team_id.write(
                        {"supervisor_ids": [(4, user.id)]}
                    )
            else:
                if user not in legacy_campaign.agent_ids:
                    legacy_campaign.write({"agent_ids": [(4, user.id)]})
                if user not in record.operational_team_id.agent_ids:
                    record.operational_team_id.write(
                        {"agent_ids": [(4, user.id)]}
                    )
        result = super().action_activate()
        for record in self:
            record.campaign_membership_id.channel_ids.with_user(
                SUPERUSER_ID
            )._mark_effective()
        return result

    def action_cancel(self):
        if any(
            record.campaign_membership_id or record.provisioning_request_id
            for record in self
        ):
            raise UserError(
                _(
                    "Prepared access must be revoked through the governed "
                    "workflow."
                )
            )
        return super().action_cancel()
