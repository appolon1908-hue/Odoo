import hashlib
import json
import uuid
from datetime import date

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

SUPER_ADMIN_GROUP = "codestra_identity_provisioning.group_provisioning_global_super_admin"
MAX_WEBRTC_ENDPOINTS = 1


class CodestraProvisioningWizard(models.TransientModel):
    """The guided Super Admin provisioning console (Milestone 2).

    A screen-by-screen wizard over models that already exist -
    ``codestra.platform.user``, ``cc.campaign.membership``,
    ``codestra.agent.channel``, ``codestra.extension.assignment``, and
    ``codestra.provisioning.request`` - this wizard creates no new
    persistent model of its own beyond its own transient state and one
    child line model for the per-campaign screen. Submitting only ever
    writes a durable ``codestra.provisioning.request`` outbox record; it
    never calls Keycloak, VICIdial, Klyrow, or Telnexa synchronously - the
    same fail-closed boundary as every other provisioning path in this
    module.
    """

    _name = "codestra.provisioning.wizard"
    _description = "Guided Agent Provisioning Console"

    state = fields.Selection(
        [
            ("person", "Person"),
            ("products", "Products"),
            ("campaigns", "Campaigns"),
            ("telephony", "Telephony"),
            ("plan_review", "Plan Review"),
            ("done", "Submitted"),
        ],
        default="person", required=True,
    )

    # Screen 1 - Person
    full_name = fields.Char(string="Full Name")
    primary_email = fields.Char(string="Primary Email")
    tenant_id = fields.Many2one("codestra.tenant", string="Tenant")
    employee_external_id = fields.Char(
        string="Employee ID",
        help="An existing HR employee's name to attach to, if known. Left "
        "blank, a new minimal hr.employee record is created from Full Name.",
    )

    # Screen 2 - Products
    odoo_access_enabled = fields.Boolean(string="Odoo CRM")
    phone_enabled = fields.Boolean(string="Phone")
    webrtc_enabled = fields.Boolean(string="WebRTC")
    sms_enabled = fields.Boolean(string="Telnexa SMS")
    email_enabled = fields.Boolean(string="Klyrow Email")

    # Screen 3 - Campaigns
    campaign_line_ids = fields.One2many(
        "codestra.provisioning.wizard.line", "wizard_id", string="Campaigns"
    )

    # Screen 4 - Telephony
    extension_mode = fields.Selection(
        [("auto", "Auto-Allocate"), ("existing", "Use Existing")],
        default="auto", string="Extension",
    )
    existing_extension_assignment_id = fields.Many2one(
        "codestra.extension.assignment", string="Existing Extension",
    )
    incoming_allowed = fields.Boolean(default=True, string="Incoming Allowed")
    outgoing_allowed = fields.Boolean(default=True, string="Outgoing Allowed")
    max_webrtc_endpoints = fields.Integer(default=1, readonly=True)

    # Screen 5 - Plan review (dry-run projection only, no side effects)
    plan_summary = fields.Text(compute="_compute_plan_summary")

    # Result, once submitted
    created_platform_user_id = fields.Many2one("codestra.platform.user", readonly=True)
    created_request_id = fields.Many2one("codestra.provisioning.request", readonly=True)

    @api.constrains("max_webrtc_endpoints")
    def _check_max_webrtc_endpoints(self):
        for wizard in self:
            if wizard.max_webrtc_endpoints != MAX_WEBRTC_ENDPOINTS:
                raise ValidationError(
                    _("The device limit cannot be increased beyond %s.")
                    % MAX_WEBRTC_ENDPOINTS
                )

    @api.depends(
        "odoo_access_enabled", "phone_enabled", "webrtc_enabled",
        "sms_enabled", "email_enabled", "extension_mode",
    )
    def _compute_plan_summary(self):
        for wizard in self:
            rows = [
                ("Keycloak", "Create / Bind"),
                ("Odoo", "Create" if wizard.odoo_access_enabled else "Skip"),
                ("VICIdial", "Create / Update" if wizard.phone_enabled else "Skip"),
                (
                    "Extension",
                    (
                        "Allocate" if wizard.extension_mode == "auto" else "Retain"
                    ) if wizard.phone_enabled else "Skip",
                ),
                ("WebRTC", "Provision" if wizard.webrtc_enabled else "Skip"),
                ("Klyrow", "Create identities" if wizard.email_enabled else "Skip"),
                ("Telnexa", "Create profiles" if wizard.sms_enabled else "Skip"),
            ]
            wizard.plan_summary = "\n".join(
                "%-10s %s" % (system, action) for system, action in rows
            )

    def _require_super_admin(self):
        if not self.env.su and not self.env.user.has_group(SUPER_ADMIN_GROUP):
            raise AccessError(
                _("Only a provisioning Super Admin may run the provisioning console.")
            )

    def action_next(self):
        self.ensure_one()
        order = ["person", "products", "campaigns", "telephony", "plan_review", "done"]
        self.state = order[order.index(self.state) + 1]
        return self._reopen()

    def action_back(self):
        self.ensure_one()
        order = ["person", "products", "campaigns", "telephony", "plan_review", "done"]
        self.state = order[order.index(self.state) - 1]
        return self._reopen()

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_submit(self):
        """Create the durable Odoo-side records only. No Keycloak, VICIdial,
        Klyrow, or Telnexa call is made here or by anything this method
        calls - codestra.provisioning.request is a request for the
        Middleware-mediated dispatch path to pick up, not a synchronous
        provisioning action.
        """
        self.ensure_one()
        self._require_super_admin()
        if self.state != "plan_review":
            raise ValidationError(_("Review the plan before submitting."))

        PlatformUser = self.env["codestra.platform.user"].with_user(SUPERUSER_ID)
        platform_user = PlatformUser.create({
            "name": self.full_name,
            "primary_email": self.primary_email,
            "tenant_id": self.tenant_id.id,
            "odoo_access_enabled": self.odoo_access_enabled,
            "phone_enabled": self.phone_enabled,
            "webrtc_enabled": self.webrtc_enabled,
            "sms_enabled": self.sms_enabled,
            "email_enabled": self.email_enabled,
        })
        if self.odoo_access_enabled:
            platform_user.action_ensure_odoo_access()

        employee = self.env["hr.employee"].search(
            [("name", "=", self.employee_external_id)], limit=1
        ) if self.employee_external_id else self.env["hr.employee"]
        if not employee:
            employee = self.env["hr.employee"].create({"name": self.full_name})

        payload = {
            "public_id": str(uuid.uuid4()),
            "full_name": self.full_name,
            "primary_email": self.primary_email,
            "tenant_id": self.tenant_id.id,
            "campaigns": [
                (line.campaign_id.id, line.role) for line in self.campaign_line_ids
            ],
        }
        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()

        default_unit = self.env["call.center.business.unit"].search([], limit=1)
        default_role_template = self.env["codestra.role.template"].search(
            [("business_unit_id", "=", default_unit.id)], limit=1
        )
        request = self.env["codestra.provisioning.request"].with_user(SUPERUSER_ID).create({
            "request_type": "onboard",
            "employee_id": employee.id,
            "target_platform_user_id": platform_user.id,
            "supervisor_id": self.env.user.id,
            "company_id": self.env.company.id,
            "business_unit_id": default_unit.id,
            "department_id": self.env["call.center.department"].search(
                [("business_unit_id", "=", default_unit.id)], limit=1
            ).id,
            "operational_team_id": self.env["call.center.team"].search(
                [("business_unit_id", "=", default_unit.id)], limit=1
            ).id,
            "role_template_id": default_role_template.id,
            "start_date": date.today(),
            "idempotency_key": payload["public_id"],
            "requested_payload_hash": payload_hash,
            "needs_company_email": self.email_enabled,
            "needs_sip_endpoint": self.phone_enabled,
        })

        extension_assignment = False
        if self.phone_enabled:
            if self.extension_mode == "existing" and self.existing_extension_assignment_id:
                extension_assignment = self.existing_extension_assignment_id
            else:
                pool = self.env["codestra.extension.pool"].search(
                    [("business_unit_id", "=", default_unit.id), ("active", "=", True)],
                    limit=1,
                )
                if pool:
                    extension_assignment = pool.reserve_extension(
                        employee, request, environment="production",
                        platform_user=platform_user,
                    )

        for line in self.campaign_line_ids:
            membership = self.env["cc.campaign.membership"].with_user(SUPERUSER_ID).search([
                ("platform_user_id", "=", platform_user.id),
                ("campaign_id", "=", line.campaign_id.id),
            ], limit=1)
            if not membership:
                membership = self.env["cc.campaign.membership"].with_user(SUPERUSER_ID).create({
                    "user_id": self.env.user.id,
                    "employee_id": employee.id,
                    "campaign_id": line.campaign_id.id,
                    "role": line.role,
                    "requested_by_id": self.env.user.id,
                    "source_ticket": request.request_number,
                    "starts_at": fields.Datetime.now(),
                    "platform_user_id": platform_user.id,
                    "vicidial_user": line.campaign_username or False,
                    "campaign_email_identity": line.campaign_email_identity or False,
                })
            Channel = self.env["codestra.agent.channel"].with_user(SUPERUSER_ID)
            for channel_type, enabled, voice in (
                ("email", line.email_access, False),
                ("sms", line.sms_access, False),
                ("phone", line.phone_access, True),
                ("webrtc", line.phone_access and self.webrtc_enabled, True),
            ):
                existing_channel = Channel.search([
                    ("employee_id", "=", employee.id), ("channel_type", "=", channel_type),
                ], limit=1)
                values = {
                    "desired_enabled": bool(enabled),
                    "incoming_allowed": self.incoming_allowed if voice else False,
                    "outgoing_allowed": self.outgoing_allowed if voice else False,
                }
                if channel_type == "phone" and extension_assignment:
                    values["extension_assignment_id"] = extension_assignment.id
                if existing_channel:
                    existing_channel.write(values)
                else:
                    Channel.create({
                        "employee_id": employee.id,
                        "membership_id": membership.id,
                        "provisioning_request_id": request.id,
                        "channel_type": channel_type,
                        **values,
                    })

        self.write({
            "state": "done",
            "created_platform_user_id": platform_user.id,
            "created_request_id": request.id,
        })
        return self._reopen()

    def action_view_provisioning_request(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "codestra.provisioning.request",
            "res_id": self.created_request_id.id,
            "view_mode": "form",
            "target": "current",
        }


class CodestraProvisioningWizardLine(models.TransientModel):
    _name = "codestra.provisioning.wizard.line"
    _description = "Guided Provisioning Console - Campaign Line"

    wizard_id = fields.Many2one(
        "codestra.provisioning.wizard", required=True, ondelete="cascade"
    )
    campaign_id = fields.Many2one("cc.campaign", required=True)
    role = fields.Selection(
        [
            ("agent", "Agent"),
            ("supervisor", "Supervisor"),
            ("configuration_manager", "Admin"),
        ],
        default="agent", required=True,
    )
    campaign_username = fields.Char()
    campaign_email_identity = fields.Char()
    phone_access = fields.Boolean()
    email_access = fields.Boolean()
    sms_access = fields.Boolean()
