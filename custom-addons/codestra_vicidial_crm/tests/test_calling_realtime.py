import os
import time
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from odoo import Command
from datetime import datetime, timedelta, timezone
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, HttpCase, tagged

from ..controllers.calling_realtime import CallingRealtimeAPI
from ..controllers import calling_realtime as controller


@tagged('post_install', '-at_install')
class TestCallingRealtimeScope(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env['call.center.business.unit'].create({'name': 'Calling Unit', 'code': 'RTUNIT'})
        cls.campaign = cls.env['codestra.vicidial.campaign'].create({'name': 'Realtime campaign', 'campaign_id': 'RTCAMP'})
        cls.canonical = cls.env['call.center.campaign'].create({
            'name': 'Realtime canonical', 'code': 'RTCAMP', 'vicidial_campaign_id': 'RTCAMP',
            'business_unit_id': cls.unit.id, 'design_automation_enabled': False})
        cls.user = cls.env['res.users'].create({
            'name': 'Realtime agent', 'login': 'realtime-agent@example.test',
            'keycloak_subject': str(uuid.uuid4()), 'codestra_tenant_id': 'RTTENANT',
            'group_ids': [Command.set([cls.env.ref('codestra_vicidial_crm.group_agent').id, cls.env.ref('call_center_core.group_call_center_user').id])],
            'call_center_business_unit_ids': [Command.set(cls.unit.ids)],
            'call_center_default_business_unit_id': cls.unit.id,
            'allowed_campaign_ids': [Command.set(cls.campaign.ids)],
        })
        cls.canonical.authorized_user_ids = cls.user
        cls.canonical.agent_ids = cls.user
        cls.agent = cls.env['codestra.vicidial.agent'].create({
            'name': 'Realtime agent', 'vicidial_user': 'RTAGENT', 'odoo_user_id': cls.user.id,
            'tenant_id': 'RTTENANT', 'campaign_ids': [Command.set(cls.campaign.ids)]})

    def setUp(self):
        super().setUp()
        self.req = SimpleNamespace(env=self.env(user=self.user.id), session={},
                                   httprequest=SimpleNamespace(headers={'Origin': 'https://odoo.example.test'},
                                                               host_url='https://odoo.example.test/'))
        patcher = patch.object(controller, 'request', self.req)
        patcher.start(); self.addCleanup(patcher.stop)
        self.api = CallingRealtimeAPI()

    def event(self):
        return {'operation_id': str(uuid.uuid4()), 'correlation_id': str(uuid.uuid4()),
                'event_id': str(uuid.uuid4()), 'sequence': 1}

    def test_scope_is_server_derived(self):
        self.assertEqual(self.api._scope(), {'tenant_id': 'RTTENANT', 'business_unit_id': 'RTUNIT',
                         'campaign_id': 'RTCAMP', 'agent_id': 'RTAGENT', 'odoo_user_id': str(self.user.id)})

    def test_duplicate_agent_fails_closed(self):
        self.agent.copy({'vicidial_user': 'RTOTHER'})
        with self.assertRaises(AccessError): self.api._scope()

    def test_disabled_agent_cannot_connect(self):
        self.agent.active = False
        with self.assertRaises(AccessError): self.api._scope()

    def test_wrong_tenant_cannot_connect(self):
        self.agent.tenant_id = 'OTHER'
        with self.assertRaises(AccessError): self.api._scope()

    def test_stale_campaign_assignment_cannot_connect(self):
        self.user.allowed_campaign_ids = False
        with self.assertRaises(AccessError): self.api._scope()

    def test_multiple_campaigns_cannot_connect(self):
        other = self.campaign.copy({'campaign_id': 'RTOTHER'})
        self.agent.campaign_ids |= other
        self.user.allowed_campaign_ids |= other
        with self.assertRaises(AccessError): self.api._scope()

    def test_cross_unit_campaign_is_rejected(self):
        other = self.unit.copy({'code': 'RTOTHER'})
        # The campaign model validates assigned users when its business unit
        # changes; authorize the existing fixture user for the alternate unit
        # first, then assert the server-derived default unit still fails closed.
        self.user.call_center_business_unit_ids |= other
        self.canonical.business_unit_id = other
        with self.assertRaises(AccessError): self.api._scope()

    def test_cross_origin_and_missing_origin_are_rejected(self):
        self.api._same_origin()
        for origin in (None, 'https://other.example.test', 'null'):
            self.req.httprequest.headers = {'Origin': origin}
            with self.assertRaises(AccessError): self.api._same_origin()

    def test_token_must_be_bound_to_current_user_subject_and_expiry(self):
        good = {'uid': self.user.id, 'subject': self.user.keycloak_subject,
                'expires_at': time.time()+45, 'access_token': 'synthetic-session-token'}
        self.req.session['codestra_calling_oidc'] = good
        self.assertEqual(self.api._token(), 'synthetic-session-token')
        for wrong in ({'uid': 0}, {'subject': 'someone-else'}, {'expires_at': 0}, {'access_token': None}):
            self.req.session['codestra_calling_oidc'] = dict(good, **wrong)
            with self.assertRaises(AccessError): self.api._token()

    def test_disabled_integration_mints_nothing(self):
        with patch.dict(os.environ, {'CODESTRA_CALLING_REALTIME_ENABLED': 'false'}), patch.object(controller.transport, 'create_session') as mint:
            self.assertFalse(self.api.bootstrap()['enabled'])
            mint.assert_not_called()

    def test_contract_mismatch_disables_integration(self):
        env = {'CODESTRA_CALLING_REALTIME_ENABLED': 'true',
               **{name: controller.transport.SCHEMA['digest'] for name in (
                   'CODESTRA_CALLING_MIDDLEWARE_DIGEST', 'CODESTRA_CALLING_GATEWAY_DIGEST', 'CODESTRA_CALLING_SDK_DIGEST')}}
        with patch.dict(os.environ, env):
            self.assertTrue(self.api._enabled())
            with patch.dict(os.environ, {'CODESTRA_CALLING_SDK_DIGEST': '0'*64}):
                self.assertFalse(self.api._enabled())

    def test_recovery_is_durable_idempotent_and_not_writable_by_agent(self):
        scope, event = self.api._scope(), self.event()
        queue = self.req.env['codestra.calling.reconciliation']
        record = queue._record_gap(scope, event)
        self.assertEqual(queue._record_gap(scope, event), record)
        self.assertEqual(record.user_id, self.user)
        with self.assertRaises(AccessError): record.with_user(self.user).write({'state': 'observed'})
        with self.assertRaises(AccessError): record.with_user(self.user).unlink()
        with self.assertRaises(AccessError): queue.create({'user_id': self.user.id})

    def test_operation_observation_does_not_release_reconciliation(self):
        scope, event = self.api._scope(), self.event()
        record = self.req.env['codestra.calling.reconciliation']._record_gap(scope, event)
        record._observe({'operation_id': event['operation_id'], 'state': 'COMPLETED', 'external_effect': True, 'calls_placed': 1})
        self.assertEqual(record.state, 'observed')
        self.assertEqual(record.operation_state, 'COMPLETED')
        self.assertEqual(record.calls_placed, '1')

    def test_large_contract_counters_do_not_rollback_durable_observations(self):
        scope, event = self.api._scope(), self.event()
        event['sequence'] = 2**40
        record = self.req.env['codestra.calling.reconciliation']._record_gap(scope, event)
        record._observe({'operation_id': event['operation_id'], 'state': 'COMPLETED', 'external_effect': True, 'calls_placed': 2**40})
        record.flush_recordset()
        self.assertEqual(record.sequence, str(2**40))
        self.assertEqual(record.calls_placed, str(2**40))

    def test_browser_event_cannot_create_an_authoritative_crm_call(self):
        event = dict(self.api._scope(), **self.event(), type='telephony.call.ringing.v1',
                     schema_version=1, occurred_at='2026-09-10T12:00:00Z', call_unique_id='synthetic-unobserved-call')
        Call = self.req.env['codestra.vicidial.call']
        before = Call.search_count([])
        with patch.object(self.api, '_enabled', return_value=True), patch.object(self.api, '_token', return_value='synthetic-user-token'):
            result = self.api.projection({'cursor': 1, 'event': event})
        self.assertTrue(result['reconciliation_required'])
        self.assertEqual(Call.search_count([]), before)

    def test_agent_status_notification_needs_no_call_projection(self):
        event = dict(self.api._scope(), **self.event(), type='telephony.agent.status-changed.v1',
                     schema_version=1, occurred_at='2026-09-10T12:00:00Z')
        with patch.object(self.api, '_enabled', return_value=True), patch.object(self.api, '_token', return_value='synthetic-user-token'):
            result = self.api.projection({'cursor': 1, 'event': event})
            self.assertEqual(result, {'reconciliation_required': False, 'agent_status_changed': True})
            event['agent_id'] = 'OTHER'
            with self.assertRaises(AccessError): self.api.projection({'cursor': 2, 'event': event})

    def test_failed_operation_read_keeps_pending_request(self):
        self.req.session['codestra_calling_oidc'] = {'uid': self.user.id, 'subject': self.user.keycloak_subject,
            'expires_at': time.time()+45, 'access_token': 'synthetic-session-token'}
        event = dict(self.api._scope(), **self.event(), type='telephony.call.ringing.v1',
                     schema_version=1, occurred_at='2026-09-10T12:00:00Z')
        with patch.object(self.api, '_enabled', return_value=True), patch.object(controller.transport, 'read_operation', side_effect=controller.transport.RealtimeUnavailable('Unavailable')):
            result = self.api.reconciliation({'cursor': 1, 'event': event})
        self.assertTrue(result['reconciliation_required'])
        self.assertEqual(result['state'], 'pending')
        self.assertEqual(self.req.env['codestra.calling.reconciliation'].search_count([('operation_id', '=', event['operation_id'])]), 1)


@tagged('post_install', '-at_install')
class TestCallingRealtimeHttp(HttpCase):
    def test_anonymous_session_is_rejected(self):
        result = self.url_open('/codestra/calling/v1/session', data='{"jsonrpc":"2.0","method":"call","params":{},"id":1}',
                               headers={'Content-Type': 'application/json', 'Origin': self.base_url()}).json()
        self.assertIn('error', result)
        self.assertNotIn('result', result)

    def test_authenticated_ticket_route_is_no_store_and_uses_server_scope(self):
        self.authenticate('admin', 'admin')
        scope = {'tenant_id': 'RTTENANT', 'business_unit_id': 'RTUNIT', 'campaign_id': 'RTCAMP',
                 'agent_id': 'RTAGENT', 'odoo_user_id': '2'}
        ticket = {'ticket': 'synthetic-one-use-http-ticket-000000',
                  'expires_at': (datetime.now(timezone.utc)+timedelta(seconds=45)).isoformat(),
                  'websocket_url': 'wss://api.codestra.co/ws/agent', 'contract_digest': controller.transport.SCHEMA['digest']}
        with patch.object(CallingRealtimeAPI, '_enabled', return_value=True), patch.object(CallingRealtimeAPI, '_scope', return_value=scope), patch.object(CallingRealtimeAPI, '_token', return_value='synthetic-user-token'), patch.object(controller.transport, 'create_session', return_value=ticket) as mint:
            response = self.url_open('/codestra/calling/v1/session', data='{"jsonrpc":"2.0","method":"call","params":{"resume_cursor":7},"id":1}',
                                     headers={'Content-Type': 'application/json', 'Origin': self.base_url()})
        self.assertEqual(response.json()['result'], {'scope': scope, 'session': ticket})
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(mint.call_args.args[:3], ('synthetic-user-token', 'RTCAMP', 7))
        self.assertNotIn('synthetic-user-token', response.text)

    def test_real_browser_uses_compiled_calling_client(self):
        self.browser_js('/odoo', '''
            (async () => {
                const client = odoo.loader.modules.get('@codestra_vicidial_crm/js/calling_realtime');
                const schema = odoo.loader.modules.get('@codestra_vicidial_crm/js/calling_schema');
                if (!client || !schema) throw new Error('Calling client missing from production assets');
                const cases = await import('/codestra_vicidial_crm/static/tests/calling_realtime_cases.js');
                const count = await cases.runCallingRealtimeCases(client, schema.callingSchema);
                if (count < 25) throw new Error('Calling browser coverage did not execute');
                console.log('CALLING_BROWSER_CASES=' + count);
                console.log('test successful');
            })().catch(error => { console.error(error); throw error; });
        ''', ready='odoo.isReady === true', login='admin', timeout=90)
