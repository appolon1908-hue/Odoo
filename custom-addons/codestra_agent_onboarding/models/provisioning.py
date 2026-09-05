import hashlib
import json
import re
import urllib.parse
import uuid

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


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
}
SYSTEM_LINK_FIELDS = {
    "campaign_membership_id",
    "provisioning_request_id",
    "provisioning_outbox_id",
    "activation_outbox_id",
}
PROVISION_EVENT = "agent.provisioning.requested.v1"
ACTIVATION_EMAIL_EVENT = "agent.activation-email.requested.v1"
EVENT_SCHEMA_VERSION = "1.0"
ONBOARDING_LINK_CAPABILITY = object()
ONBOARDING_VERSION_CAPABILITY = object()


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

    _integration_uuid_unique = models.Constraint(
        "unique(integration_uuid)",
        "Agent-onboarding integration UUIDs must be unique.",
    )
    _desired_state_version_positive = models.Constraint(
        "check(desired_state_version > 0)",
        "Agent-onboarding desired-state versions must be positive.",
    )

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            values.setdefault("integration_uuid", str(uuid.uuid4()))
            values.setdefault("desired_state_version", 1)
        return super().create(values_list)

    def write(self, values):
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
    )
    def _check_assignment_scope(self):
        for record in self:
            if record.activation_email and not EMAIL_PATTERN.fullmatch(
                record.activation_email.strip()
            ):
                raise ValidationError(_("The activation email address is invalid."))
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

    def _ensure_agent_user(self):
        self.ensure_one()
        employee = self.employee_id.with_user(SUPERUSER_ID)
        unit = self.campaign_id.legacy_campaign_id.business_unit_id
        email = self.activation_email.strip().lower()
        user = employee.user_id.with_user(SUPERUSER_ID)
        Users = self.env["res.users"].with_user(SUPERUSER_ID).with_context(active_test=False)
        if not user:
            collision = Users.search([("login", "=ilike", email)], limit=1)
            if collision:
                raise ValidationError(
                    _(
                        "The requested login already exists. Use the reviewed identity "
                        "adoption workflow instead of attaching it automatically."
                    )
                )
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

    def _provisioning_idempotency_key(self):
        self.ensure_one()
        return _sha256(
            "|".join(
                (
                    "agent-onboarding-v1",
                    self.integration_uuid,
                    str(self.employee_id.id),
                    self.campaign_id.workspace_uuid,
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
                or self.campaign_id.legacy_campaign_id not in existing.campaign_ids
            ):
                raise ValidationError(
                    _("The provisioning idempotency key is already bound.")
                )
            return existing
        return Request.create(
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
                    (6, 0, self.campaign_id.legacy_campaign_id.ids)
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
                "needs_keycloak": self.needs_keycloak,
                "needs_vicidial": self.needs_vicidial,
                "idempotency_key": key,
                "cc_membership_id": membership.id,
            }
        )

    def _event_context(self):
        self.ensure_one()
        return {
            "onboarding_uuid": self.integration_uuid,
            "onboarding_number": self.name,
            "desired_state_version": self.desired_state_version,
            "provisioning_request_id": self.provisioning_request_id.id,
            "provisioning_request_number": (
                self.provisioning_request_id.request_number
            ),
            "membership_uuid": self.campaign_membership_id.identity_uuid,
            "employee_id": self.employee_id.codestra_employee_number,
            "odoo_user_id": self.employee_id.user_id.id,
            "login_identifier": self.employee_id.user_id.login,
            "business_unit_code": self.business_unit_id.code,
            "campaign_code": self.campaign_id.code,
            "campaign_workspace_uuid": self.campaign_id.workspace_uuid,
            "campaign_scope_version": self.campaign_id.scope_version,
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
            record._assert_assignment_ready()
            if record.provisioning_request_id and record.campaign_membership_id:
                continue
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
        if values:
            membership.write(values)

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
        return {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_type": PROVISION_EVENT,
            **self._event_context(),
            "recipient_email": self.activation_email.strip().lower(),
            "targets": targets,
            "controls": {
                "create_disabled": True,
                "activate_immediately": False,
                "send_activation_email": False,
                "plaintext_password_allowed": False,
                "browser_campaign_selection_allowed": False,
                "change_agent_campaign": False,
                "production_dialing": False,
                "live_call_control": False,
            },
        }

    def action_start_provisioning(self):
        self._require_state("approved", "provisioning")
        self._require_global_administrator()
        for record in self:
            if record.provisioning_outbox_id:
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
            if request_record.state != "provisioning":
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
            payload = record._provisioning_event_payload()
            event = record._create_integration_event(
                PROVISION_EVENT,
                payload,
                _sha256(
                    "%s|%s|%s"
                    % (
                        record.integration_uuid,
                        record.desired_state_version,
                        PROVISION_EVENT,
                    )
                ),
            )
            record._write_system_links(
                {
                    "state": "provisioning",
                    "provisioning_outbox_id": event.id,
                    "provisioning_started_at": fields.Datetime.now(),
                }
            )
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
        return super().action_activate()

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
