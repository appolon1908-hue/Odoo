from odoo import fields, models


class SyncPreviewWizard(models.TransientModel):
    _name = "codestra.sync.preview.wizard"
    result = fields.Text(readonly=True)
