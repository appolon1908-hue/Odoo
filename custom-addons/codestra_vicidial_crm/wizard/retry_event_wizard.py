from odoo import fields, models


class RetryEventWizard(models.TransientModel):
    _name = "codestra.retry.event.wizard"
    event_id = fields.Many2one("codestra.integration.event", required=True)

    def action_retry(self):
        self.event_id.write({"state": "retry", "last_error": False})
        return {"type": "ir.actions.act_window_close"}
