/** @odoo-module **/
// Pure cases run both in the source gate (Node) and in the real Odoo browser.
export async function runCallingRealtimeCases({ CallingEventStream, CallingRealtimeClient, validateCalling }, schema) {
    let count = 0;
    const assert = (value, label) => { if (!value) throw new Error(label); count++; };
    const fails = (fn, label) => { let rejected = false; try { fn(); } catch { rejected = true; } assert(rejected, label); };
    const scope = {tenant_id:'tenant', business_unit_id:'unit', campaign_id:'campaign', agent_id:'agent', odoo_user_id:'42'};
    const envelope = (sequence = 1, cursor = sequence, overrides = {}) => ({cursor, event:{...scope,
        event_id:`11111111-1111-4111-8111-${String(sequence).padStart(12, '0')}`,
        operation_id:'22222222-2222-4222-8222-222222222222', correlation_id:'33333333-3333-4333-8333-333333333333',
        type:'telephony.call.ringing.v1', schema_version:1, occurred_at:'2026-09-10T12:00:00Z', sequence, ...overrides}});
    let stream = new CallingEventStream(scope);
    const first = envelope(1, 10);
    assert(stream.accept(first), 'first event');
    assert(stream.cursor === 0 && stream.sequences.size === 0, 'uncommitted events must replay after disconnect');
    stream.commit(first);
    assert(!stream.accept({...first, cursor: 11}) && stream.cursor === 11, 'identical duplicate advances replay cursor only');
    fails(() => stream.accept(envelope(1,12,{duration_seconds:99})), 'conflicting duplicate');
    assert(stream.accept(envelope(2,20)), 'stream cursor gaps for other agents are allowed');
    stream.commit(envelope(2,20));
    fails(() => stream.accept(envelope(4,21)), 'operation sequence gap');
    assert(stream.cursor === 20 && stream.blocked, 'gap freezes cursor');
    fails(() => stream.accept(envelope(3,22)), 'late missing event cannot silently resume');
    for (const key of Object.keys(scope)) fails(() => new CallingEventStream(scope).accept(envelope(1,1,{[key]:'other'})), `wrong ${key}`);
    fails(() => new CallingEventStream(scope).accept(envelope(1,1,{schema_version:true})), 'boolean version');
    fails(() => new CallingEventStream(scope).accept(envelope(1,1,{sequence:true})), 'boolean sequence');
    fails(() => new CallingEventStream(scope).accept(envelope(1,1,{extra:'field'})), 'closed event schema');
    fails(() => new CallingEventStream(scope).accept(envelope(1,1,{odoo_user_id:undefined})), 'missing Odoo identity');
    stream = new CallingEventStream(scope); stream.commit(first);
    fails(() => stream.accept(envelope(2,9)), 'regressing stream cursor');
    let socket, sessionCalls = 0, writes = [], calls = [], states = [], recoveries = [];
    class FakeSocket {
        constructor(url) { this.url=url; socket=this; }
        send(value) { writes.push(JSON.parse(value)); }
        close() { this.closed=true; }
    }
    const session = () => ({scope, session:{ticket:'synthetic-one-use-ticket-for-browser-tests',
        expires_at:new Date(Date.now()+45000).toISOString(), websocket_url:'wss://api.codestra.co/ws/agent', contract_digest:schema.digest}});
    const client = new CallingRealtimeClient({scope, Socket:FakeSocket,
        getSession:async cursor => { sessionCalls++; assert(cursor === 0,'initial replay cursor'); return session(); },
        project:async () => ({reconciliation_required:false,call:{call_id:'persisted-call'}}),
        reconcile:async value => recoveries.push(value), onCall:async call=>calls.push(call), onState:state=>states.push(state)});
    await client.connect(); socket.onopen();
    assert(writes.length === 1 && writes[0].type === 'auth' && !socket.url.includes('ticket='), 'one-use first auth frame');
    socket.onmessage({data:JSON.stringify({type:'realtime.connected.v1',correlation_id:'33333333-3333-4333-8333-333333333333',occurred_at:'2026-09-10T12:00:00Z'})});
    socket.onmessage({data:JSON.stringify(envelope())}); await client.chain;
    assert(calls.length === 1 && calls[0].call_id === 'persisted-call' && client.stream.cursor === 1, 'persisted projection drives UI');
    socket.onmessage({data:JSON.stringify(envelope(3,3))}); await client.chain;
    assert(client.stopped && recoveries.length === 1 && calls.length === 1, 'gap queues recovery without a second screen pop');
    assert(client.stream.cursor === 1, 'gap never acknowledges missing state');
    client.stop();
    let resolveSession;
    const late = new CallingRealtimeClient({scope, Socket:FakeSocket,
        getSession:()=>new Promise(resolve=>{resolveSession=resolve;}), project:async()=>{}, reconcile:async()=>{}, onCall:async()=>{}, onState:()=>{}});
    const connecting = late.connect(); const oldSocket=socket; late.stop(); resolveSession(session()); await connecting;
    assert(socket === oldSocket, 'logout ignores a late ticket response');
    const legacy = new CallingRealtimeClient({scope, Socket:FakeSocket, getSession:async()=>session(), project:async()=>{}, reconcile:async()=>{}, onCall:async()=>{}, onState:()=>{}});
    await legacy.connect(); socket.onmessage({data:JSON.stringify({type:'authenticated',session_id:'legacy'})});
    assert(legacy.stopped, 'legacy handshake cannot enable the canonical stream'); legacy.stop();
    const notifications = [];
    const statusClient = new CallingRealtimeClient({scope, Socket:FakeSocket, getSession:async()=>session(),
        project:async value => value.event.type === 'telephony.agent.status-changed.v1'
            ? {reconciliation_required:false, agent_status_changed:true}
            : {reconciliation_required:false, call:{call_id:'next-call'}},
        reconcile:async()=>{throw new Error('Routine status notification must not reconcile');},
        onCall:async call=>notifications.push(call), onState:()=>{}});
    await statusClient.connect();
    socket.onmessage({data:JSON.stringify({type:'realtime.connected.v1',correlation_id:'33333333-3333-4333-8333-333333333333',occurred_at:'2026-09-10T12:00:00Z'})});
    socket.onmessage({data:JSON.stringify(envelope(1,1,{type:'telephony.agent.status-changed.v1'}))});
    await statusClient.chain;
    assert(!statusClient.stopped && statusClient.stream.cursor === 1 && notifications.length === 0, 'status notification has no call projection');
    socket.onmessage({data:JSON.stringify(envelope(2,2))}); await statusClient.chain;
    assert(!statusClient.stopped && notifications.length === 1 && statusClient.stream.cursor === 2, 'call notifications continue after agent status');
    statusClient.stop();
    fails(()=>validateCalling({...session().session,websocket_url:'wss://other.invalid/ws/agent'},schema.schemas.RealtimeSession),'unexpected socket destination');
    return count;
}
