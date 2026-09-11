import uuid

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

SUPER_ADMIN_GROUP = "codestra_identity_provisioning.group_provisioning_global_super_admin"


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
    tenant_id = fields.Char(required=True, index=True, tracking=True)
    keycloak_subject = fields.Char(copy=False, index=True)

    odoo_access_enabled = fields.Boolean(default=False, tracking=True)
    odoo_user_id = fields.Many2one("res.users", ondelete="restrict", copy=False)

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

    def _require_super_admin(self):
        if not self.env.su and not self.env.user.has_group(SUPER_ADMIN_GROUP):
            raise AccessError(
                _("Only a provisioning Super Admin may change platform users.")
            )

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

    def action_ensure_odoo_access(self):
        """Create the ``res.users`` record for this platform user if (and
        only if) ``odoo_access_enabled`` is set and none exists yet. A
        standalone Phone/Telnexa/Klyrow customer with access disabled is
        left exactly as-is - this is deliberately a no-op for them.
        """
        for record in self:
            if not record.odoo_access_enabled or record.odoo_user_id:
                continue
            user = self.env["res.users"].with_context(no_reset_password=True).create(
                {
                    "name": record.name,
                    "login": record.primary_email,
                    "email": record.primary_email,
                }
            )
            record.odoo_user_id = user.id
