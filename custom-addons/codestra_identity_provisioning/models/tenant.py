from odoo import _, api, fields, models
from odoo.exceptions import AccessError

SUPER_ADMIN_GROUP = "codestra_identity_provisioning.group_provisioning_global_super_admin"
PLATFORM_ADMIN_GROUP = "codestra_identity_provisioning.group_platform_admin"


class CodestraTenant(models.Model):
    """The top-level customer/organization boundary a platform user belongs
    to - distinct from ``call.center.business.unit``/``cc.business.unit``,
    which scope internal call-center organization (departments, campaigns,
    extension pools) rather than which external customer owns the data.
    """

    _name = "codestra.tenant"
    _description = "Platform Tenant"
    _inherit = ["mail.thread"]
    _order = "name"

    name = fields.Char(required=True, tracking=True)
    code = fields.Char(required=True, index=True, tracking=True)
    status = fields.Selection(
        [("active", "Active"), ("suspended", "Suspended")],
        default="active", required=True, tracking=True,
    )
    platform_user_ids = fields.One2many("codestra.platform.user", "tenant_id")

    _code_unique = models.Constraint(
        "unique(code)", "Tenant codes must be unique."
    )

    def _require_super_admin(self):
        if not (
            self.env.su
            or self.env.user.has_group(SUPER_ADMIN_GROUP)
            or self.env.user.has_group(PLATFORM_ADMIN_GROUP)
        ):
            raise AccessError(_("Only a Platform Admin may change tenants."))

    @api.model_create_multi
    def create(self, values_list):
        self._require_super_admin()
        return super().create(values_list)

    def write(self, values):
        self._require_super_admin()
        return super().write(values)

    def unlink(self):
        self._require_super_admin()
        return super().unlink()
