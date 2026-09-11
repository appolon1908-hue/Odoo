import uuid

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

SUPER_ADMIN_GROUP = "codestra_identity_provisioning.group_provisioning_global_super_admin"
PLATFORM_ADMIN_GROUP = "codestra_identity_provisioning.group_platform_admin"
PLATFORM_OPERATOR_GROUP = "codestra_identity_provisioning.group_platform_operator"
TENANT_ADMIN_GROUP = "codestra_identity_provisioning.group_tenant_admin"
TENANT_ADMIN_CREATE_FIELDS = {
    "name", "primary_email", "tenant_id",
    "phone_enabled", "webrtc_enabled", "sms_enabled", "email_enabled",
}
TENANT_ADMIN_WRITE_FIELDS = {
    "name", "primary_email", "status",
    "phone_enabled", "webrtc_enabled", "sms_enabled", "email_enabled",
}
TENANT_ADMIN_RESTRICTED_FIELDS = {
    "platform_role", "tenant_id", "odoo_access_enabled", "odoo_user_id",
}


class CodestraPlatformUser(models.Model):
    """The platform-wide human identity, decoupled from ``res.users``.

    Not every real-world customer of the platform needs (or should get) an
    Odoo login: a standalone Phone, Telnexa (SMS), or Klyrow (email)
    customer is a genuine platform identity with no reason to ever touch
    Odoo. ``odoo_access_enabled`` is the single switch that decides whether
    an Odoo user is ever created for this identity; when it is ``False``,
    ``odoo_user_id`` stays empty and ``action_ensure_odoo_access`` is a
    no-op. This model does not itself create Keycloak identities, send
    email/SMS, or provision phone/WebRTC access - it is the Odoo-side
    record of who this person is and which channels they are entitled to;
    ``codestra.agent.channel`` (per campaign membership) and
    ``codestra.extension.assignment`` (per environment) carry the actual
    provisioning state.
    """

    _name = "codestra.platform.user"
    _description = "Platform Identity"
    _inherit = ["mail.thread"]
    _order = "name"

    public_id = fields.Char(
        required=True, copy=False, index=True, readonly=True,
        default=lambda self: str(uuid.uuid4()),
    )
    name = fields.Char(required=True, tracking=True)
    primary_email = fields.Char(required=True, tracking=True)
    tenant_id = fields.Many2one(
        "codestra.tenant", required=True, ondelete="restrict", index=True, tracking=True
    )
    keycloak_subject = fields.Char(copy=False, index=True)

    odoo_access_enabled = fields.Boolean(default=False, tracking=True)
    odoo_user_id = fields.Many2one("res.users", ondelete="restrict", copy=False)

    platform_role = fields.Selection(
        [
            ("none", "None"),
            ("platform_operator", "Platform Operator"),
            ("platform_admin", "Platform Admin"),
        ],
        default="none", required=True, tracking=True,
        help="Global scope, independent of tenant/campaign roles - see "
        "codestra.tenant.membership (tenant_admin/member) and "
        "cc.campaign.membership (supervisor/agent) for the other two "
        "authorization scopes. Deliberately not a hierarchy: a "
        "platform_operator does not imply campaign or tenant authority, "
        "and this field alone grants nothing in Odoo until "
        "action_ensure_odoo_access() has linked a res.users record for "
        "_sync_platform_role_group() to assign the matching group to.",
    )
    tenant_membership_ids = fields.One2many(
        "codestra.tenant.membership", "platform_user_id", string="Tenant Memberships"
    )

    phone_enabled = fields.Boolean(default=False, tracking=True)
    webrtc_enabled = fields.Boolean(default=False, tracking=True)
    sms_enabled = fields.Boolean(default=False, tracking=True)
    email_enabled = fields.Boolean(default=False, tracking=True)

    status = fields.Selection(
        [("active", "Active"), ("suspended", "Suspended"), ("terminated", "Terminated")],
        default="active", required=True, tracking=True,
    )
    provisioning_state = fields.Selection(
        [
            ("requested", "Requested"),
            ("provisioning", "Provisioning"),
            ("provisioned", "Provisioned"),
            ("effective", "Effective"),
            ("failed", "Failed"),
        ],
        default="requested", required=True, tracking=True,
    )

    last_verified_at = fields.Datetime(copy=False)
    last_error = fields.Char(copy=False)

    phone_assignment_ids = fields.One2many(
        "codestra.extension.assignment", "platform_user_id", string="Phone Assignments"
    )

    keycloak_status = fields.Selection(
        [("ready", "Ready"), ("not_ready", "Not Ready")],
        compute="_compute_keycloak_status",
    )

    _public_id_unique = models.Constraint(
        "unique(public_id)", "Platform user public identifiers must be unique."
    )
    _primary_email_unique = models.Constraint(
        "unique(primary_email)", "A primary email may belong to only one platform user."
    )

    @api.constrains("odoo_user_id", "odoo_access_enabled")
    def _check_odoo_access_gate(self):
        for record in self:
            if record.odoo_user_id and not record.odoo_access_enabled:
                raise ValidationError(
                    _(
                        "An Odoo user cannot be linked while Odoo access is "
                        "disabled for this platform user."
                    )
                )

    @api.depends("keycloak_subject")
    def _compute_keycloak_status(self):
        for record in self:
            record.keycloak_status = "ready" if record.keycloak_subject else "not_ready"

    def _has_full_platform_authority(self):
        return (
            self.env.su
            or self.env.user.has_group(SUPER_ADMIN_GROUP)
            or self.env.user.has_group(PLATFORM_ADMIN_GROUP)
        )

    def _require_super_admin(self):
        if not self._has_full_platform_authority():
            raise AccessError(
                _("Only a provisioning Super Admin or Platform Admin may change platform users.")
            )

    def _tenant_admin_tenant_ids(self):
        return set(self.env.user.codestra_tenant_admin_ids.ids)

    def _has_tenant_admin_scope(self):
        admin_tenant_ids = self._tenant_admin_tenant_ids()
        return bool(admin_tenant_ids) and all(
            record.tenant_id.id in admin_tenant_ids for record in self
        )

    def _validate_tenant_admin_create(self, values_list):
        admin_tenant_ids = self._tenant_admin_tenant_ids()
        if not admin_tenant_ids:
            raise AccessError(_("You are not assigned as an administrator of a tenant."))
        for values in values_list:
            unexpected = set(values) - TENANT_ADMIN_CREATE_FIELDS
            if unexpected:
                raise AccessError(
                    _("Tenant Admins may not set protected fields: %s")
                    % ", ".join(sorted(unexpected))
                )
            tenant_id = values.get("tenant_id")
            if not tenant_id or tenant_id not in admin_tenant_ids:
                raise AccessError(
                    _("A Tenant Admin may create users only inside an assigned tenant.")
                )

    @api.model_create_multi
    def create(self, values_list):
        if self._has_full_platform_authority():
            records = super().create(values_list)
            records._sync_platform_role_group()
            self.env["codestra.tenant.membership"]._sync_tenant_admin_group_for_users(
                records.mapped("odoo_user_id")
            )
            return records
        if not self.env.user.has_group(TENANT_ADMIN_GROUP):
            self._require_super_admin()
        self._validate_tenant_admin_create(values_list)
        records = super().create(values_list)
        # A tenant-created identity is a tenant member by default. It cannot
        # grant itself platform or tenant-admin authority; Platform Admin is
        # still required to promote or assign privileged roles.
        self.env["codestra.tenant.membership"].create([
            {
                "platform_user_id": record.id,
                "tenant_id": record.tenant_id.id,
                "role": "member",
            }
            for record in records
        ])
        return records

    def write(self, values):
        previous_odoo_users = self.mapped("odoo_user_id")
        if self._has_full_platform_authority():
            pass
        elif (
            set(values) <= {"status"}
            and self.env.user.has_group(PLATFORM_OPERATOR_GROUP)
        ):
            pass
        elif (
            set(values) <= TENANT_ADMIN_WRITE_FIELDS
            and self.env.user.has_group(TENANT_ADMIN_GROUP)
            and self._has_tenant_admin_scope()
        ):
            pass
        else:
            raise AccessError(
                _("You are not authorized to change these fields on this platform user.")
            )
        result = super().write(values)
        if "platform_role" in values or "odoo_user_id" in values:
            self._sync_platform_role_group()
        if "odoo_user_id" in values:
            self.env["codestra.tenant.membership"]._sync_tenant_admin_group_for_users(
                previous_odoo_users | self.mapped("odoo_user_id")
            )
        return result

    def unlink(self):
        self._require_super_admin()
        return super().unlink()

    def action_suspend(self):
        """Suspend this platform user. Odoo-side status only - it does not
        itself disable any external system; Middleware's own suspend
        endpoint (POST .../requests/{id}/suspend) is the real external
        effect, driven from the linked codestra.provisioning.request, not
        from this button directly. write() itself is the real
        authorization check here (full authority, or a Platform Operator,
        or a Tenant Admin within their own tenant's scope) - deliberately
        not re-narrowed to super-admin-only here.
        """
        self.write({"status": "suspended"})

    def action_reactivate(self):
        for record in self:
            if record.status != "suspended":
                raise ValidationError(_("Only a suspended platform user may be reactivated."))
        self.write({"status": "active"})

    def action_ensure_odoo_access(self):
        """Create the ``res.users`` record for this platform user if (and
        only if) ``odoo_access_enabled`` is set and none exists yet. A
        standalone Phone/Telnexa/Klyrow customer with access disabled is
        left exactly as-is - this is deliberately a no-op for them.
        """
        self._require_super_admin()
        for record in self:
            if not record.odoo_access_enabled or record.odoo_user_id:
                continue
            # Creating res.users is gated by Odoo's own narrow "Access
            # Rights" group, which this module's Super Admin does not (and
            # should not) automatically hold - _require_super_admin() above
            # is the real authorization check; this elevation only lets an
            # already-authorized caller reach the resource it needs.
            user = self.env["res.users"].with_user(SUPERUSER_ID).with_context(
                no_reset_password=True
            ).create(
                {
                    "name": record.name,
                    "login": record.primary_email,
                    "email": record.primary_email,
                }
            )
            record.odoo_user_id = user.id
            record._sync_platform_role_group()
            self.env["codestra.tenant.membership"]._sync_tenant_admin_group_for_users(
                record.odoo_user_id
            )

    _PLATFORM_ROLE_GROUP_XMLID = {
        "platform_operator": "codestra_identity_provisioning.group_platform_operator",
        "platform_admin": "codestra_identity_provisioning.group_platform_admin",
    }

    def _sync_platform_role_group(self):
        """Project ``platform_role`` onto the linked ``res.users``' groups.

        A no-op for any record with no ``odoo_user_id`` (standalone
        Phone/Telnexa/Klyrow customers, or a platform_admin/operator who
        has not been given Odoo access at all - platform_role alone never
        creates one). Removes the *other* platform-role group first so a
        role change never leaves a stale group behind.
        """
        Group = self.env["res.groups"].sudo()
        operator_group = Group.browse(
            self.env.ref(
                self._PLATFORM_ROLE_GROUP_XMLID["platform_operator"]
            ).id
        )
        admin_group = Group.browse(
            self.env.ref(self._PLATFORM_ROLE_GROUP_XMLID["platform_admin"]).id
        )
        for record in self:
            if not record.odoo_user_id:
                continue
            user = record.odoo_user_id.sudo()
            target = self._PLATFORM_ROLE_GROUP_XMLID.get(record.platform_role)
            if target == self._PLATFORM_ROLE_GROUP_XMLID["platform_operator"]:
                user.write({"group_ids": [(4, operator_group.id), (3, admin_group.id)]})
            elif target == self._PLATFORM_ROLE_GROUP_XMLID["platform_admin"]:
                user.write({"group_ids": [(4, admin_group.id), (3, operator_group.id)]})
            else:
                user.write({"group_ids": [(3, operator_group.id), (3, admin_group.id)]})
