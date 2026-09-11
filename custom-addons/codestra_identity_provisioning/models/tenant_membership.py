from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

SUPER_ADMIN_GROUP = "codestra_identity_provisioning.group_provisioning_global_super_admin"
PLATFORM_ADMIN_GROUP = "codestra_identity_provisioning.group_platform_admin"
PLATFORM_OPERATOR_GROUP = "codestra_identity_provisioning.group_platform_operator"
TENANT_ADMIN_GROUP = "codestra_identity_provisioning.group_tenant_admin"


class CodestraTenantMembership(models.Model):
    """Who administers (or merely belongs to) one customer tenant.

    Nothing before this tracked "tenant admin" as a real, assignable role -
    codestra.tenant itself only carries name/code/status. This is
    deliberately a *new* model rather than an extension of anything
    existing: cc.campaign.membership already covers the campaign-scoped
    supervisor/agent roles, and codestra.platform.user already carries the
    global platform_role, but neither one represents "administers tenant
    COD" - a distinct, tenant-scoped authorization boundary.
    """

    _name = "codestra.tenant.membership"
    _description = "Tenant Administration Membership"
    _order = "tenant_id, platform_user_id"

    platform_user_id = fields.Many2one(
        "codestra.platform.user", required=True, ondelete="cascade", index=True
    )
    tenant_id = fields.Many2one(
        "codestra.tenant", required=True, ondelete="cascade", index=True
    )
    role = fields.Selection(
        [("tenant_admin", "Tenant Admin"), ("member", "Member")],
        default="member", required=True,
    )
    active = fields.Boolean(default=True)
    valid_from = fields.Datetime()
    valid_until = fields.Datetime()

    _platform_user_tenant_unique = models.Constraint(
        "unique(platform_user_id, tenant_id)",
        "A platform user may have only one membership per tenant.",
    )

    def _has_platform_admin_authority(self):
        return (
            self.env.su
            or self.env.user.has_group(SUPER_ADMIN_GROUP)
            or self.env.user.has_group(PLATFORM_ADMIN_GROUP)
        )

    def _tenant_admin_tenant_ids(self):
        return set(self.env.user.codestra_tenant_admin_ids.ids)

    def _require_platform_admin(self):
        if not self._has_platform_admin_authority():
            raise AccessError(
                _("Only a Platform Admin may create or promote Tenant Admins.")
            )

    def _require_tenant_admin_scope(self, tenant_id):
        if self._has_platform_admin_authority():
            return
        if (
            self.env.user.has_group(TENANT_ADMIN_GROUP)
            and tenant_id in self._tenant_admin_tenant_ids()
        ):
            return
        raise AccessError(
            _("Tenant Admins may manage memberships only inside their assigned tenant.")
        )

    def _check_platform_user_alignment(self, values):
        tenant_id = values.get("tenant_id")
        platform_user_id = values.get("platform_user_id")
        if not tenant_id or not platform_user_id:
            raise ValidationError(
                _("A tenant membership needs both a tenant and a platform user.")
            )
        platform_user = self.env["codestra.platform.user"].browse(platform_user_id).exists()
        if not platform_user or platform_user.tenant_id.id != tenant_id:
            raise ValidationError(
                _("The platform user and tenant membership must belong to the same tenant.")
            )

    @api.model_create_multi
    def create(self, values_list):
        if self._has_platform_admin_authority():
            return super().create(values_list)
        if not self.env.user.has_group(TENANT_ADMIN_GROUP):
            raise AccessError(
                _("Only a Platform Admin or Tenant Admin may create memberships.")
            )
        for values in values_list:
            if values.get("role", "member") != "member":
                self._require_platform_admin()
            self._require_tenant_admin_scope(values.get("tenant_id"))
            self._check_platform_user_alignment(values)
        return super().create(values_list)

    def write(self, values):
        if self._has_platform_admin_authority():
            return super().write(values)
        if not self.env.user.has_group(TENANT_ADMIN_GROUP):
            raise AccessError(_("Only a Platform Admin may change tenant memberships."))
        if any(membership.role == "tenant_admin" for membership in self):
            self._require_platform_admin()
        if set(values) & {"platform_user_id", "tenant_id", "role"}:
            raise AccessError(
                _("Tenant Admins cannot reassign membership identity or privilege.")
            )
        if not all(
            membership.tenant_id.id in self._tenant_admin_tenant_ids()
            for membership in self
        ):
            self._require_tenant_admin_scope(False)
        return super().write(values)

    @api.constrains("platform_user_id", "tenant_id")
    def _check_tenant_alignment(self):
        for membership in self:
            self._check_platform_user_alignment({
                "tenant_id": membership.tenant_id.id,
                "platform_user_id": membership.platform_user_id.id,
            })



class ResUsers(models.Model):
    """The record-rule-visible projection of "which tenants does this Odoo
    user administer", mirroring codestra_cc_security's existing
    user.cc_allowed_campaign_ids / cc_supervised_campaign_ids pattern for
    the tenant scope instead of the campaign scope.
    """

    _inherit = "res.users"

    codestra_tenant_admin_ids = fields.Many2many(
        "codestra.tenant", compute="_compute_codestra_tenant_admin_ids",
    )

    def _compute_codestra_tenant_admin_ids(self):
        memberships = self.env["codestra.tenant.membership"].sudo().search([
            ("role", "=", "tenant_admin"),
            ("active", "=", True),
            ("platform_user_id.odoo_user_id", "in", self.ids),
        ])
        by_user = {}
        for membership in memberships:
            by_user.setdefault(membership.platform_user_id.odoo_user_id.id, []).append(
                membership.tenant_id.id
            )
        for user in self:
            user.codestra_tenant_admin_ids = by_user.get(user.id, [])
