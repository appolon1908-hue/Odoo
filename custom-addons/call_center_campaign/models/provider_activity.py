from odoo import models


class ResPartner(models.Model):
    _inherit = "res.partner"

    def _mail_get_operation_for_mail_message_operation(self, message_operation):
        operations = super()._mail_get_operation_for_mail_message_operation(
            message_operation
        )
        if message_operation == "create" and self.env.user.has_group(
            "call_center_campaign.group_provider_activity_service"
        ):
            allowed_unit_ids = set(
                self.env.user.call_center_business_unit_ids.ids
            )
            return {
                partner: "read"
                for partner in self
                if partner.business_unit_id.id in allowed_unit_ids
            }
        return operations
