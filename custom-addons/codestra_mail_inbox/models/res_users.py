from odoo import api, Command, models, _
from odoo.exceptions import UserError


class ResUsers(models.Model):
    _inherit = "res.users"

    @api.model
    def _provision_codestra_mail_ingestion_service(self):
        """Attach only the machine-ingestion role to the existing service user."""
        raw_user_id = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("codestra.middleware.service_user_id", "")
        )
        if not raw_user_id:
            return False
        if not raw_user_id.isdigit():
            raise UserError(_("Middleware service user authority is invalid."))
        service_user = self.sudo().browse(int(raw_user_id)).exists()
        if not service_user or not service_user.active:
            raise UserError(_("Active middleware service user is required."))
        ingestion_group = self.env.ref(
            "codestra_mail_inbox.group_mail_ingestion_service"
        )
        service_user.write({"group_ids": [Command.link(ingestion_group.id)]})
        return True
