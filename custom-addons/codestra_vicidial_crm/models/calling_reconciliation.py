"""Durable, scoped recovery requests; operation reads never authorize redial."""
import json

from odoo import api, fields, models
from odoo.exceptions import AccessError


class CallingReconciliation(models.Model):
    _name = 'codestra.calling.reconciliation'
    _description = 'Calling event reconciliation request'
    _order = 'id desc'

    user_id = fields.Many2one('res.users', required=True, ondelete='restrict', index=True)
    tenant_id = fields.Char(required=True, index=True)
    campaign_id = fields.Char(required=True, index=True)
    agent_id = fields.Char(required=True)
    operation_id = fields.Char(required=True, index=True)
    correlation_id = fields.Char(required=True)
    event_id = fields.Char(required=True)
    sequence = fields.Char(required=True, size=20)
    state = fields.Selection([('pending', 'Pending operation read'), ('observed', 'Operation observed; CDR required')],
                             default='pending', required=True)
    operation_state = fields.Char()
    external_effect = fields.Boolean()
    calls_placed = fields.Char(size=20)
    observation_json = fields.Text()
    last_checked_at = fields.Datetime()

    _calling_reconcile_identity_unique = models.Constraint(
        'UNIQUE(user_id, tenant_id, campaign_id, agent_id, operation_id)',
        'A reconciliation request already exists for this operation and scope.')

    @api.private
    def _record_gap(self, scope, event):
        owner = self.env.uid
        queue = self.sudo()
        domain = [('user_id', '=', owner)] + [(key, '=', scope[key]) for key in ('tenant_id', 'campaign_id', 'agent_id')]
        record = queue.search(domain + [('operation_id', '=', event['operation_id'])], limit=1)
        if record:
            if record.correlation_id != event['correlation_id']:
                raise AccessError('Reconciliation identity conflicts with earlier evidence.')
            return record
        if queue.search_count(domain, limit=100) >= 100:
            raise AccessError('Calling reconciliation requires operator attention.')
        return queue.create(dict(user_id=owner, **{key: scope[key] for key in ('tenant_id', 'campaign_id', 'agent_id')},
                                 **{key: event[key] for key in ('operation_id', 'correlation_id', 'event_id', 'sequence')}))

    @api.private
    def _observe(self, result):
        self.ensure_one()
        self.sudo().write({'state': 'observed', 'operation_state': result['state'],
                          'external_effect': result['external_effect'], 'calls_placed': str(result['calls_placed']),
                          'observation_json': json.dumps(result, sort_keys=True),
                          'last_checked_at': fields.Datetime.now()})
