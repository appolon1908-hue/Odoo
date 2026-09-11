from odoo import _, api, fields, models
from odoo.exceptions import AccessError

SUPER_ADMIN_GROUP = "codestra_identity_provisioning.group_provisioning_global_super_admin"
PLATFORM_ADMIN_GROUP = "codestra_identity_provisioning.group_platform_admin"


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

    def _require_platform_admin(self):
        if not self.env.su and not self.env.user.has_group(SUPER_ADMIN_GROUP) \
                and not self.env.user.has_group(PLATFORM_ADMIN_GROUP):
            raise AccessError(
                _("Only a Platform Admin may create additional Tenant Admins.")
            )

    @api.model_create_multi
    def create(self, values_list):
        if any(values.get("role") == "tenant_admin" for values in values_list):
            self._require_platform_admin()
        return super().create(values_list)

    def write(self, values):
        if values.get("role") == "tenant_admin" or any(
            membership.role == "tenant_admin" for membership in self
        ):
            self._require_platform_admin()
        return super().write(values)


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
