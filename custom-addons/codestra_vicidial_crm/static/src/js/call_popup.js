/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

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
        });
        this.openedCalls = new Set();
        this.bus.addEventListener("notification", ({ detail }) => {
            for (const item of detail || []) {
                const type = item.type || item[1];
                const payload = item.payload || item[2];
                if (type === "codestra.call" && payload) {
                    this.handleCall(payload);
                }
            }
        });
        onWillStart(async () => {
            try {
                const current = await this.rpc("/codestra/call-control/v1/current", {});
                if (current) await this.handleCall(current);
            } catch (error) {
                this.ui.error = error.message || "Phone unavailable";
            }
        });
    }

    key() { return crypto.randomUUID(); }

    async handleCall(payload) {
        if (this.ui.call && payload.call_id !== this.ui.call.call_id && !this.terminal) return;
        this.ui.call = payload;
        this.ui.notes = payload.notes || this.ui.notes;
        this.ui.matches = [];
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
            this.ui.error = error.message || "Call control failed";
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
