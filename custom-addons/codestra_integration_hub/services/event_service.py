from odoo import api, models


class IntegrationEventService(models.AbstractModel):
    _name = "codestra.integration.event.service"
    _description = "Codestra Integration Event Lifecycle Service"

    @api.model
    def register_event(self, **values):
        return self.env["codestra.integration.event"].register_event(**values)
