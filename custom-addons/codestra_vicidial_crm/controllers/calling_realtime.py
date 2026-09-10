"""Same-origin BFF for the canonical calling read side.

The browser receives a one-use ticket only. A service account or a stored Odoo
OAuth token must never substitute for this browser session's OIDC principal.
"""
import os
import time
import uuid

from odoo import fields, http
from odoo.exceptions import AccessError, UserError
from odoo.http import request

from ..models import calling_realtime as transport


class CallingRealtimeAPI(http.Controller):
    @staticmethod
    def _enabled():
        return (os.environ.get('CODESTRA_CALLING_REALTIME_ENABLED') == 'true'
                and all(os.environ.get(name) == transport.SCHEMA['digest'] for name in (
                    'CODESTRA_CALLING_MIDDLEWARE_DIGEST', 'CODESTRA_CALLING_GATEWAY_DIGEST',
                    'CODESTRA_CALLING_SDK_DIGEST')))

    @staticmethod
    def _same_origin():
        incoming = request.httprequest
        if incoming.headers.get('Origin') != incoming.host_url.rstrip('/'):
            raise AccessError('A same-origin calling session is required.')

    @staticmethod
    def _scope():
        user = request.env.user
        if (not user.active or user.share or not user.keycloak_subject or not user.codestra_tenant_id
                or not user.has_group('codestra_vicidial_crm.group_agent')):
            raise AccessError('An active assigned calling identity is required.')
        agents = request.env['codestra.vicidial.agent'].search([
            ('odoo_user_id', '=', user.id), ('active', '=', True)], limit=2)
        if len(agents) != 1 or agents.tenant_id != user.codestra_tenant_id:
            raise AccessError('Calling agent assignment is ambiguous or stale.')
        campaigns = agents.campaign_ids.filtered('active') & user.allowed_campaign_ids.filtered('active')
        unit = user.call_center_default_business_unit_id
        if (len(campaigns) != 1 or not unit or not unit.active
                or unit not in user.call_center_business_unit_ids or unit.company_id not in user.company_ids):
            raise AccessError('One campaign and an authorized business unit are required.')
        # When consolidated campaigns are installed, the legacy projection cannot
        # override their business-unit authority.
        if 'call.center.campaign' in request.env:
            canonical = request.env['call.center.campaign'].search([
                '|', ('code', '=', campaigns.campaign_id),
                ('vicidial_campaign_id', '=', campaigns.campaign_id)], limit=2)
            if (len(canonical) != 1 or not canonical.active or canonical.business_unit_id != unit
                    or user not in canonical.authorized_user_ids):
                raise AccessError('Canonical campaign assignment does not match.')
        scope = {'tenant_id': user.codestra_tenant_id, 'business_unit_id': unit.code,
                 'campaign_id': campaigns.campaign_id, 'agent_id': agents.vicidial_user,
                 'odoo_user_id': str(user.id)}
        try:
            event = transport.SCHEMA['schemas']['AgentEventEnvelope']['properties']['event']
            for key, value in scope.items():
                transport.validate(value, event['properties'][key])
        except transport.RealtimeUnavailable:
            raise AccessError('Calling identity is not contract compatible.') from None
        return scope

    @staticmethod
    def _token():
        session = request.session.get('codestra_calling_oidc') or {}
        user = request.env.user
        if (session.get('uid') != user.id or session.get('subject') != user.keycloak_subject
                or type(session.get('expires_at')) not in (int, float)
                or session['expires_at'] <= time.time() + 5
                or not isinstance(session.get('access_token'), str)):
            raise AccessError('Sign in through Keycloak again to connect calling events.')
        return session['access_token']

    @http.route('/codestra/calling/v1/bootstrap', type='jsonrpc', auth='user', methods=['POST'])
    def bootstrap(self):
        self._same_origin()
        if not self._enabled():
            return {'enabled': False, 'required': os.environ.get('CODESTRA_CALLING_REALTIME_ENABLED') == 'true',
                    'state': 'integration_unavailable'}
        scope = self._scope()
        self._token()
        return {'enabled': True, 'scope': scope, 'contract_digest': transport.SCHEMA['digest']}

    @http.route('/codestra/calling/v1/session', type='jsonrpc', auth='user', methods=['POST'])
    def session(self, resume_cursor=0):
        self._same_origin()
        if not self._enabled():
            raise UserError('Calling integration has not passed its contract gates.')
        scope = self._scope()
        token = self._token()
        try:
            # No browser-supplied tenant, agent, role, endpoint, token, or campaign.
            session = transport.create_session(token, scope['campaign_id'], resume_cursor,
                                               str(uuid.uuid4()), str(uuid.uuid4()))
        except transport.RealtimeUnavailable:
            raise UserError('Calling session unavailable. Reconnect after integration recovery.') from None
        request.future_response.headers['Cache-Control'] = 'no-store'
        request.future_response.headers['Pragma'] = 'no-cache'
        return {'session': session, 'scope': scope}

    @http.route('/codestra/calling/v1/projection', type='jsonrpc', auth='user', methods=['POST'])
    def projection(self, envelope):
        self._same_origin()
        if not self._enabled():
            raise AccessError('Calling integration is unavailable.')
        scope = self._scope()
        self._token()
        try:
            transport.validate(envelope, transport.SCHEMA['schemas']['AgentEventEnvelope'])
        except transport.RealtimeUnavailable:
            raise AccessError('Invalid calling event.') from None
        event = envelope['event']
        if any(event.get(key) != value for key, value in scope.items()):
            raise AccessError('Calling event scope does not match this session.')
        # Socket messages are notifications, not authority to mutate CRM. Only a
        # persisted Middleware projection can supply lead data or advance the UI.
        call = request.env['codestra.vicidial.call'].search([
            ('correlation_id', '=', event['correlation_id']),
            ('asterisk_uniqueid', '=', event.get('call_unique_id') or '__missing__'),
            ('tenant_id', '=', scope['tenant_id']), ('business_unit_id', '=', scope['business_unit_id']),
            ('campaign_code', '=', scope['campaign_id']),
            ('agent_id.odoo_user_id', '=', request.env.uid),
            ('agent_id.vicidial_user', '=', scope['agent_id']),
            ('keycloak_subject', '=', request.env.user.keycloak_subject)], limit=2)
        if len(call) != 1 or call.last_event_id != event['event_id'] or call.sequence != event['sequence']:
            return {'reconciliation_required': True}
        payload = call.agent_payload()
        payload['call_control_enabled'] = False
        payload['transfer_control_enabled'] = False
        return {'reconciliation_required': False, 'call': payload}

    @http.route('/codestra/calling/v1/reconciliation', type='jsonrpc', auth='user', methods=['POST'])
    def reconciliation(self, envelope=None):
        self._same_origin()
        if not self._enabled():
            raise AccessError('Calling integration is unavailable.')
        scope = self._scope()
        token = self._token()
        if envelope is None:
            request.env['codestra.calling.reconciliation']._record_gap(scope, {
                'operation_id': 'stream', 'correlation_id': 'stream',
                'event_id': 'replay-gap', 'sequence': 0,
            })
            return {'reconciliation_required': True, 'state': 'pending'}
        try:
            transport.validate(envelope, transport.SCHEMA['schemas']['AgentEventEnvelope'])
        except transport.RealtimeUnavailable:
            raise AccessError('Invalid calling event.') from None
        event = envelope['event']
        if any(event.get(key) != value for key, value in scope.items()):
            raise AccessError('Calling event scope does not match this session.')
        queue = request.env['codestra.calling.reconciliation']._record_gap(scope, event)
        if queue.last_checked_at and (fields.Datetime.now() - queue.last_checked_at).total_seconds() < 30:
            return {'reconciliation_required': True, 'state': queue.state}
        queue.sudo().write({'last_checked_at': fields.Datetime.now()})
        try:
            result = transport.read_operation(token, event['operation_id'], event['correlation_id'])
            queue._observe(result)
        except transport.RealtimeUnavailable:
            pass  # Commit the pending recovery request even when the authority is unavailable.
        return {'reconciliation_required': True, 'state': queue.state}
