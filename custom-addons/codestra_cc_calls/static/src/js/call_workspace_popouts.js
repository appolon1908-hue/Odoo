/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { deserializeDateTime, formatDateTime, serializeDateTime } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";

const { DateTime } = luxon;
const OPEN_CALLBACK_STATES = [
    "draft", "scheduled", "ready", "in_progress", "missed", "recovery", "blocked",
];

export class CodestraCallWorkspacePopouts extends Component {
    static template = "codestra_cc_calls.CallWorkspacePopouts";
    static props = [];

    setup() {
        this.action = useService("action");
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.state = useState({
            active: null,
            appointments: [],
            callbacks: [],
            reminders: [],
            error: null,
            isDisplayed: false,
            loading: false,
        });
        this.loadVersion = 0;
        onWillStart(async () => {
            this.state.isDisplayed = (
                await user.hasGroup("codestra_cc_security.group_cc_campaign_agent") ||
                await user.hasGroup("codestra_cc_security.group_cc_campaign_supervisor") ||
                await user.hasGroup("codestra.group_agent") ||
                await user.hasGroup("codestra.group_supervisor")
            );
        });
    }

    onKeydown(event) {
        if (event.key === "Escape" && this.state.active) {
            event.stopPropagation();
            this.close();
        }
    }

    async toggle(kind) {
        if (this.state.active === kind) {
            this.close();
            return;
        }
        this.state.active = kind;
        await this.load(kind);
    }

    close() {
        this.state.active = null;
        this.state.error = null;
        this.loadVersion += 1;
    }

    async load(kind) {
        const version = ++this.loadVersion;
        this.state.loading = true;
        this.state.error = null;
        const now = DateTime.now();
        try {
            if (kind === "calendar") {
                this.state.appointments = await this.orm.searchRead(
                    "cc.appointment",
                    [
                        ["scheduled_start", ">=", serializeDateTime(now.startOf("day"))],
                        ["scheduled_start", "<=", serializeDateTime(now.plus({ days: 7 }).endOf("day"))],
                        ["state", "not in", ["cancelled", "completed"]],
                    ],
                    ["name", "scheduled_start", "scheduled_end", "state", "customer_profile_id", "campaign_id"],
                    { limit: 8, order: "scheduled_start asc, id asc" }
                );
            } else if (kind === "reminders") {
                this.state.reminders = await this.orm.searchRead(
                    "cc.reminder",
                    [
                        ["scheduled_at", "<=", serializeDateTime(now.plus({ days: 1 }))],
                        ["state", "=", "held"],
                    ],
                    ["appointment_id", "callback_id", "event_type", "scheduled_at", "state"],
                    { limit: 8, order: "scheduled_at asc, id asc" }
                );
            } else {
                this.state.callbacks = await this.orm.searchRead(
                    "cc.callback",
                    [
                        ["scheduled_at", ">=", serializeDateTime(now.minus({ hours: 1 }))],
                        ["state", "in", OPEN_CALLBACK_STATES],
                    ],
                    ["name", "scheduled_at", "state", "customer_profile_id", "campaign_id", "priority"],
                    { limit: 8, order: "scheduled_at asc, priority desc, id asc" }
                );
            }
        } catch (error) {
            this.state.error = error.message || "The scheduling panel is temporarily unavailable.";
            this.notification.add("Codestra scheduling data could not be loaded.", { type: "danger" });
        } finally {
            if (version === this.loadVersion) {
                this.state.loading = false;
            }
        }
    }

    async refresh() {
        if (this.state.active) {
            await this.load(this.state.active);
        }
    }

    formatDateTime(value) {
        return value ? formatDateTime(deserializeDateTime(value)) : "";
    }

    relationLabel(value) {
        return Array.isArray(value) ? value[1] : "";
    }

    async openRecord(model, id) {
        this.close();
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: model,
            res_id: id,
            views: [[false, "form"]],
        });
    }

    async openAction(xmlId) {
        this.close();
        await this.action.doAction(xmlId);
    }

    async createAppointment() {
        this.close();
        await this.action.doAction({
            type: "ir.actions.act_window",
            name: "Schedule Appointment",
            res_model: "cc.appointment",
            views: [[false, "form"]],
            target: "new",
            context: {
                default_scheduled_start: serializeDateTime(DateTime.now().plus({ hours: 1 })),
                default_scheduled_end: serializeDateTime(DateTime.now().plus({ hours: 1, minutes: 30 })),
                default_customer_timezone: DateTime.local().zoneName,
            },
        });
    }

    async createCallback() {
        this.close();
        await this.action.doAction({
            type: "ir.actions.act_window",
            name: "Schedule Callback",
            res_model: "cc.callback",
            views: [[false, "form"]],
            target: "new",
            context: {
                default_scheduled_at: serializeDateTime(DateTime.now().plus({ hours: 1 })),
                default_customer_timezone: DateTime.local().zoneName,
            },
        });
    }

    get title() {
        return {
            calendar: "Appointment Calendar",
            reminders: "Reminder Center",
            scheduler: "Callback Scheduler",
        }[this.state.active] || "Call Operations";
    }
}

registry.category("systray").add(
    "codestra_appointments.popouts",
    { Component: CodestraCallWorkspacePopouts },
    { sequence: 18, force: true }
);
