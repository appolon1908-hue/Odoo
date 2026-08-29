from odoo import api, models


class IntegrationIdempotencyService(models.AbstractModel):
    _name = "codestra.integration.idempotency.service"
    _description = "Codestra Integration Idempotency Service"

    @api.model
    def register_idempotent_event(self, *args, **kwargs):
        return self.env["codestra.integration.idempotency"].register_idempotent_event(*args, **kwargs)
