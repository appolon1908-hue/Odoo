/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

// Odoo's JSON-RPC dispatcher always sets the top-level error message to the
// literal string "Odoo Server Error" (see odoo/http.py JsonRPCDispatcher.
// handle_error) for any exception besides NotFound/SessionExpired. The actual
// exception message (e.g. an AccessError raised by an agent-binding check)
// only lives in `error.data.message`, so callers must read that first or the
// agent sees the generic wrapper text instead of the real reason.
function errorMessage(error, fallback) {
    return error?.data?.message || error?.message || fallback;
}

export class CodestraCallPopup extends Component {
    static template = "codestra_vicidial_crm.CallPopup";

    setup() {
        this.rpc = rpc;
        this.bus = useService("bus_service");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.ui = useState({
            call: null, busy: false, error: "", notes: "", disposition: "",
            matches: [], history: [], callbackAt: "", callbackTimezone: "UTC", callbackReason: "",
            dialpad: {
                open: false, number: "", campaignId: "TEST_SYN", enabled: false,
                busy: false, error: "", reason: "", status: "Loading dialer…", matches: [],
            },
        });
        this.openedCalls = new Set();
        this.bus.addEventListener("notification", ({ detail }) => {
            for (const item of detail || []) {
                const type = item.type || item[1];
                const payload = item.payload || item[2];
                if (type === "codestra.call.result" && payload) {
                    this.notification.add(payload.reason || "Call request was not accepted", {
                        type: payload.outcome === "unknown" ? "warning" : "danger",
                        sticky: true,
                    });
                    continue;
                }
                if (type === "codestra.call" && payload) {
                    this.handleCall(payload);
                }
            }
        });
        onWillStart(async () => {
            await this.loadDialpad();
            try {
                const current = await this.rpc("/codestra/call-control/v1/current", {});
                if (current) await this.handleCall(current);
            } catch (error) {
                this.ui.error = errorMessage(error, "Phone unavailable");
            }
        });
    }

    get dialpadKeys() {
        return ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"];
    }

    async loadDialpad() {
        try {
            const state = await this.rpc("/codestra/call-control/v1/dialpad", {});
            Object.assign(this.ui.dialpad, {
                campaignId: state.campaign_id || "TEST_SYN",
                enabled: Boolean(state.enabled),
                reason: state.reason || "",
                status: state.state === "ready" ? "Ready" : "Disabled",
            });
        } catch (error) {
            this.ui.dialpad.enabled = false;
            this.ui.dialpad.status = "Unavailable";
            this.ui.dialpad.reason = errorMessage(error, "Dialer is unavailable.");
        }
    }

    toggleDialpad() {
        this.ui.dialpad.open = !this.ui.dialpad.open;
    }

    appendDialpadDigit(digit) {
        if (!/^\d$/.test(digit) || this.ui.dialpad.number.length >= 15) return;
        this.ui.dialpad.number += digit;
        this.ui.dialpad.error = "";
        this.ui.dialpad.matches = [];
    }

    backspaceDialpad() {
        this.ui.dialpad.number = this.ui.dialpad.number.slice(0, -1);
        this.ui.dialpad.error = "";
        this.ui.dialpad.matches = [];
    }

    clearDialpad() {
        this.ui.dialpad.number = "";
        this.ui.dialpad.error = "";
        this.ui.dialpad.matches = [];
        this.ui.dialpad.status = this.ui.dialpad.enabled ? "Ready" : "Disabled";
    }

    onDialpadKeydown(event) {
        if (/^\d$/.test(event.key)) {
            event.preventDefault();
            this.appendDialpadDigit(event.key);
        } else if (event.key === "Backspace") {
            event.preventDefault();
            this.backspaceDialpad();
        } else if (event.key === "Enter") {
            event.preventDefault();
            this.dialpadCall();
        }
    }

    async resolveDialpad() {
        if (!this.ui.dialpad.number) {
            this.ui.dialpad.error = "Enter a phone number.";
            return null;
        }
        try {
            const result = await this.rpc("/codestra/call-control/v1/match", {
                number: this.ui.dialpad.number,
                campaign_code: this.ui.dialpad.campaignId,
            });
            this.ui.dialpad.matches = result.matches || [];
            if (result.match !== "exact") {
                this.ui.dialpad.error = result.match === "ambiguous"
                    ? "More than one CRM record matches this number."
                    : "No authorized CRM record matches this number.";
                return null;
            }
            this.ui.dialpad.status = this.ui.dialpad.matches[0].name || "Exact CRM match";
            this.ui.dialpad.error = "";
            return result;
        } catch (error) {
            this.ui.dialpad.error = errorMessage(error, "Number lookup failed.");
            return null;
        }
    }

    async dialpadCall() {
        if (this.ui.dialpad.busy) return;
        if (!this.ui.dialpad.enabled) {
            this.ui.dialpad.error = this.ui.dialpad.reason || "Outbound calling is disabled.";
            return;
        }
        const match = await this.resolveDialpad();
        if (!match) return;
        this.ui.dialpad.busy = true;
        try {
            const result = await this.rpc("/codestra/call-control/v1/outbound", {
                destination: this.ui.dialpad.number,
                campaign_id: this.ui.dialpad.campaignId,
                idempotency_key: this.key(),
            });
            this.ui.dialpad.open = false;
            this.ui.dialpad.status = "Call queued; awaiting authoritative events";
            await this.handleCall(result.call);
            this.notification.add("Call request accepted; waiting for telephony confirmation.", { type: "info" });
        } catch (error) {
            this.ui.dialpad.error = errorMessage(error, "Call request failed.");
        } finally {
            this.ui.dialpad.busy = false;
        }
    }

    key() { return crypto.randomUUID(); }

    async handleCall(payload) {
        if (this.ui.call && payload.call_id !== this.ui.call.call_id && !this.terminal) return;
        this.ui.call = payload;
        this.ui.notes = payload.notes || this.ui.notes;
        this.ui.matches = [];
        this.ui.error = "";
        // Called unawaited from the bus listener on every authoritative call-state
        // push (ringing/answering/connected/...), so a transient failure here -
        // e.g. an agent/tenant binding race right as the call connects - must
        // never propagate as an unhandled rejection. Surface it on the popup
        // instead of letting the generic "Odoo Server Error" dialog appear.
        try {
            if (!payload.customer && !payload.lead && payload.caller_number) {
                const result = await this.rpc("/codestra/call-control/v1/match", {
                    number: payload.caller_number,
                    call_id: payload.call_id,
                    campaign_code: payload.campaign,
                    business_unit_id: payload.business_unit,
                });
                this.ui.matches = result.matches || [];
                if (result.match === "exact") await this.openRecord(result.matches[0].model, result.matches[0].id, true);
            } else if (payload.lead) {
                await this.openRecord("crm.lead", payload.lead.id, true);
            } else if (payload.customer) {
                await this.openRecord("res.partner", payload.customer.id, true);
            }
            const history = await this.rpc(`/codestra/call-control/v1/calls/${payload.call_id}/history`, { limit: 20 });
            this.ui.history = history.items || [];
        } catch (error) {
            this.ui.error = errorMessage(error, "Call details are temporarily unavailable.");
        }
    }

    async control(action, extra = {}) {
        if (!this.ui.call || this.ui.busy) return;
        this.ui.busy = true;
        this.ui.error = "";
        try {
            await this.rpc(`/codestra/call-control/v1/calls/${this.ui.call.call_id}/${action}`, {
                idempotency_key: this.key(), ...extra,
            });
            this.notification.add(`${action[0].toUpperCase() + action.slice(1)} requested; awaiting Asterisk confirmation`, { type: "info" });
        } catch (error) {
            this.ui.error = errorMessage(error, "Call control failed");
        } finally {
            this.ui.busy = false;
        }
    }

    async saveCallback() {
        if (!this.ui.call || !this.ui.callbackAt || !this.ui.callbackReason) return;
        const result = await this.rpc(`/codestra/call-control/v1/calls/${this.ui.call.call_id}/callbacks`, {
            scheduled_at: this.ui.callbackAt,
            timezone: this.ui.callbackTimezone,
            reason: this.ui.callbackReason,
            idempotency_key: this.key(),
        });
        if (result.dispatch_enabled) throw new Error("Callback dispatch must remain disabled during certification.");
        this.notification.add("Callback saved; no call was dispatched", { type: "success" });
    }

    async saveNotes() {
        await this.rpc(`/codestra/call-control/v1/calls/${this.ui.call.call_id}/notes`, {
            notes: this.ui.notes, idempotency_key: this.key(),
        });
        this.notification.add("Call notes saved", { type: "success" });
    }

    async saveDisposition() {
        await this.rpc(`/codestra/call-control/v1/calls/${this.ui.call.call_id}/disposition`, {
            disposition_code: this.ui.disposition, notes: this.ui.notes,
            idempotency_key: this.key(),
        });
        this.notification.add("Disposition saved", { type: "success" });
    }

    async openRecord(model, id, automatic = false) {
        if (!model || !id || !this.ui.call) return;
        const key = `${this.ui.call.call_id}:${model}:${id}`;
        if (automatic && this.openedCalls.has(key)) return;
        const open = async () => {
            this.openedCalls.add(key);
            await this.actionService.doAction({ type: "ir.actions.act_window", res_model: model, res_id: id, views: [[false, "form"]] });
            await this.rpc(`/codestra/call-control/v1/calls/${this.ui.call.call_id}/record-opened`, { model, record_id: id });
        };
        if (automatic && navigator.locks?.request) {
            await navigator.locks.request(`codestra-screen-pop:${key}`, { ifAvailable: true }, async (lock) => {
                if (lock) await open();
            });
        } else {
            await open();
        }
    }

    get terminal() { return ["completed", "failed", "missed", "rejected", "cancelled", "transferred"].includes(this.ui.call?.state); }
}

registry.category("main_components").add("codestra_call_popup", { Component: CodestraCallPopup });
