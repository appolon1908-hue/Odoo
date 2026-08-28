from odoo import fields, models


class VicidialCallCompatibility(models.Model):
    _inherit = 'codestra.vicidial.call'

    partner_id = fields.Many2one('res.partner', index=True)
    vicidial_lead_id = fields.Integer(index=True)
    list_id = fields.Integer(index=True)
    phone_raw = fields.Char()
    phone_e164 = fields.Char(index=True)
    vicidial_user = fields.Char(index=True)
    call_start = fields.Datetime(index=True)
    call_end = fields.Datetime()
    total_seconds = fields.Integer(default=0)
    disposition_code = fields.Char(index=True)
    sync_status = fields.Selection(
        [('pending', 'Pending'), ('clean', 'Clean'), ('error', 'Error')],
        default='pending',
        index=True,
    )
    raw_payload = fields.Text()


class VicidialSyncEvent(models.Model):
    _name = 'codestra.vicidial.sync.event'
    _description = 'Codestra VICIdial Synchronization Event'
    _order = 'created_at desc, id desc'

    name = fields.Char(required=True, index=True)
    middleware_event_id = fields.Char(required=True, index=True)
    event_type = fields.Char(required=True, index=True)
    source = fields.Char(required=True)
    target = fields.Char(required=True)
    status = fields.Selection(
        [('pending', 'Pending'), ('processed', 'Processed'), ('failed', 'Failed')],
        required=True,
        default='pending',
        index=True,
    )
    payload = fields.Text()
    error_message = fields.Text()
    retry_count = fields.Integer(default=0)
    created_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    processed_at = fields.Datetime()

    _middleware_event_id_unique = models.Constraint(
        'UNIQUE(middleware_event_id)', 'Middleware event ID must be unique.'
    )
