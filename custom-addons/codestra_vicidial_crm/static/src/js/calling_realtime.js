/** @odoo-module **/
import { callingSchema } from './calling_schema';

const MAX_BYTES = 262144;
const BACKOFF = [1000, 2000, 4000, 8000, 15000, 30000];
const UUID = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
export function validateCalling(value, schema) {
    const require = (condition) => { if (!condition) throw new Error('Invalid calling message'); };
    if (schema.type === 'object') {
        require(value !== null && typeof value === 'object' && !Array.isArray(value));
        require((schema.required || []).every(key => Object.hasOwn(value, key)));
        if (schema.additionalProperties === false) require(Object.keys(value).every(key => Object.hasOwn(schema.properties, key)));
        for (const [key, item] of Object.entries(value)) validateCalling(item, schema.properties?.[key] || {});
    } else if (schema.type === 'string') {
        require(typeof value === 'string' && value.length >= (schema.minLength || 0) && value.length <= (schema.maxLength || MAX_BYTES));
        if (schema.pattern) require(new RegExp(schema.pattern).test(value) && !value.endsWith('\n'));
        if (schema.format === 'uuid') require(UUID.test(value));
        if (schema.format === 'date-time') require(/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value)));
    } else if (schema.type === 'integer') {
        require(Number.isSafeInteger(value) && value >= (schema.minimum || 0) && value <= (schema.maximum || Number.MAX_SAFE_INTEGER));
    } else if (schema.type === 'boolean') require(typeof value === 'boolean');
    if (Object.hasOwn(schema, 'const')) require(value === schema.const);
    if (schema.enum) require(schema.enum.includes(value));
}

const stable = value => JSON.stringify(value, Object.keys(value).sort());

export class CallingEventStream {
    constructor(scope) {
        this.scope = scope;
        this.cursor = 0;
        this.sequences = new Map();
        this.processed = new Map();
        this.blocked = false;
    }
    accept(envelope) {
        if (this.blocked) throw new Error('Reconciliation required');
        validateCalling(envelope, callingSchema.schemas.AgentEventEnvelope);
        const event = envelope.event;
        if (Object.entries(this.scope).some(([key, value]) => event[key] !== value)) throw new Error('Calling scope mismatch');
        const previous = this.processed.get(event.event_id);
        const fingerprint = stable(event);
        if (previous) {
            if (previous !== fingerprint) throw new Error('Event identity conflict');
            this.cursor = Math.max(this.cursor, envelope.cursor);
            return false;
        }
        const last = this.sequences.get(event.operation_id) || 0;
        // Stream cursors need not be contiguous: other agents share the stream.
        // A per-operation sequence gap freezes all advancement until REST/CDR
        // reconciliation. No speculative reordering or UI state is applied.
        if (envelope.cursor <= this.cursor || event.sequence !== last + 1) {
            this.blocked = true;
            throw new Error('Reconciliation required');
        }
        if (this.sequences.size >= 256 && !this.sequences.has(event.operation_id)) {
            this.blocked = true;
            throw new Error('Reconciliation required');
        }
        // Caller commits sequence, deduplication identity and cursor together,
        // only after its persisted projection and UI delivery agree.
        return true;
    }
    commit(envelope) {
        const event = envelope.event;
        this.sequences.set(event.operation_id, event.sequence);
        this.processed.set(event.event_id, stable(event));
        if (this.processed.size > 4096) this.processed.delete(this.processed.keys().next().value);
        this.cursor = Math.max(this.cursor, envelope.cursor);
    }
}

export class CallingRealtimeClient {
    constructor({ scope, getSession, project, reconcile, onCall, onState, Socket = WebSocket }) {
        Object.assign(this, {scope, getSession, project, reconcile, onCall, onState, Socket});
        this.stream = new CallingEventStream(scope);
        this.stopped = false;
        this.generation = 0;
        this.retries = 0;
        this.pending = 0;
        this.chain = Promise.resolve();
    }
    clearTimers() {
        clearTimeout(this.timer); clearTimeout(this.authTimer); clearTimeout(this.expiryTimer);
        this.timer = this.authTimer = this.expiryTimer = undefined;
    }
    stop(state = 'Disconnected') {
        this.stopped = true; this.generation += 1;
        this.clearTimers(); this.socket?.close(1000);
        this.onState(state);
    }
    async connect() {
        if (this.stopped) return;
        const generation = ++this.generation;
        this.onState(this.retries ? 'Reconnecting' : 'Connecting');
        try {
            const result = await this.getSession(this.stream.cursor);
            if (this.stopped || generation !== this.generation) return;
            if (stable(result.scope) !== stable(this.scope)) { this.stop('Authorization changed'); return; }
            const session = result.session;
            validateCalling(session, callingSchema.schemas.RealtimeSession);
            const expires = Date.parse(session.expires_at) - Date.now();
            if (session.contract_digest !== callingSchema.digest || expires <= 0 || expires > 60000) {
                this.stop('Integration mismatch'); return;
            }
            const socket = new this.Socket(session.websocket_url);
            this.socket = socket;
            let authenticated = false;
            this.authTimer = setTimeout(() => socket.close(1000), 5000);
            this.expiryTimer = setTimeout(() => socket.close(1000), expires);
            socket.onopen = () => {
                if (this.stopped || generation !== this.generation) return;
                // Ticket is sent once in the first frame, never in a URL or log.
                socket.send(JSON.stringify({type: 'auth', ticket: session.ticket}));
                session.ticket = '';
            };
            socket.onmessage = message => {
                if (this.stopped || generation !== this.generation) return;
                let value;
                try {
                    if (typeof message.data !== 'string' || new TextEncoder().encode(message.data).length > MAX_BYTES) throw new Error();
                    value = JSON.parse(message.data);
                    if (value?.type) {
                        validateCalling(value, callingSchema.schemas.RealtimeControlEvent);
                        if (value.type === 'realtime.connected.v1' && !authenticated && !value.reconciliation_required) {
                            authenticated = true; this.retries = 0; clearTimeout(this.authTimer); this.onState('Connected'); return;
                        }
                        this.stop(value.type === 'realtime.authorization-revoked.v1' ? 'Authorization revoked' : 'Reconciliation required');
                        this.reconcile(null).catch(() => {});
                        return;
                    }
                    if (!authenticated || ++this.pending > 256) throw new Error();
                } catch { this.stop('Reconciliation required'); return; }
                this.chain = this.chain.then(async () => {
                    if (this.stopped || generation !== this.generation) { this.pending -= 1; return; }
                    try {
                        if (!this.stream.accept(value)) return;
                        const projection = await this.project(value);
                        if (this.stopped || generation !== this.generation) return;
                        const agentNotification = value.event.type === 'telephony.agent.status-changed.v1';
                        if (projection.reconciliation_required) throw new Error();
                        if (agentNotification) {
                            if (projection.agent_status_changed !== true || projection.call !== undefined) throw new Error();
                        } else {
                            if (!projection.call || projection.agent_status_changed) throw new Error();
                            await this.onCall(projection.call);
                        }
                        if (!this.stopped && generation === this.generation) this.stream.commit(value);
                    } catch {
                        this.stop('Reconciliation required');
                        // The server validates scope again and records a durable
                        // request before attempting an authorized operation read.
                        try { await this.reconcile(value); } catch { /* Remain stopped. */ }
                    } finally { this.pending -= 1; }
                });
            };
            socket.onerror = () => socket.close(1000);
            socket.onclose = event => {
                if (this.stopped || generation !== this.generation) return;
                this.clearTimers(); this.generation += 1;
                if ([1008, 4401, 4403].includes(event.code)) this.stop('Authorization expired');
                else this.schedule();
            };
        } catch {
            if (!this.stopped && generation === this.generation) this.schedule();
        }
    }
    schedule() {
        if (this.stopped || this.timer !== undefined) return;
        if (this.retries >= BACKOFF.length) { this.stop('Offline'); return; }
        this.onState('Reconnecting');
        this.timer = setTimeout(() => { this.timer = undefined; this.connect(); }, BACKOFF[this.retries++]);
    }
}
