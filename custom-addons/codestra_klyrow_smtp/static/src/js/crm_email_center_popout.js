/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { deserializeDateTime, formatDateTime } from "@web/core/l10n/dates";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";

export class CodestraCrmEmailCenterPopout extends Component {
    static template = "codestra_klyrow_smtp.CrmEmailCenterPopout";
    static props = [];

    setup() {
        this.action = useService("action");
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.state = useState({
            composeEnabled: false,
            deliveryReady: false,
            error: null,
            isDisplayed: false,
            isOpen: false,
            items: [],
            loading: false,
            openCount: 0,
            profiles: [],
            waitingCount: 0,
        });
        this.loadVersion = 0;

        onWillStart(async () => {
            this.state.isDisplayed =
                (await user.hasGroup("codestra_cc_security.group_cc_scoped_user")) ||
                (await user.hasGroup("codestra_cc_security.group_cc_global_administrator"));
        });
    }

    onKeydown(event) {
        if (event.key === "Escape" && this.state.isOpen) {
            event.stopPropagation();
            this.close();
        }
    }

    async toggle() {
        if (this.state.isOpen) {
            this.close();
            return;
        }
        this.state.isOpen = true;
        await this.load();
    }

    close() {
        this.state.isOpen = false;
        this.state.error = null;
        this.loadVersion += 1;
    }

    async load() {
        const version = ++this.loadVersion;
        this.state.loading = true;
        this.state.error = null;
        try {
            const snapshot = await this.orm.call(
                "cc.mail.thread",
                "crm_email_center_snapshot",
                [],
                { limit: 8 }
            );
            if (version !== this.loadVersion) {
                return;
            }
            this.state.items = snapshot.items || [];
            this.state.openCount = snapshot.open_count || 0;
            this.state.waitingCount = snapshot.waiting_count || 0;
            this.state.deliveryReady = Boolean(snapshot.delivery_ready);
            this.state.composeEnabled = Boolean(snapshot.compose_enabled);
            this.state.profiles = snapshot.profiles || [];
        } catch (error) {
            if (version !== this.loadVersion) {
                return;
            }
            this.state.error =
                error.message || "The CRM Email Center is temporarily unavailable.";
            this.notification.add("Campaign email data could not be loaded.", {
                type: "danger",
            });
        } finally {
            if (version === this.loadVersion) {
                this.state.loading = false;
            }
        }
    }

    async refresh() {
        await this.load();
    }

    formatDateTime(value) {
        return value ? formatDateTime(deserializeDateTime(value)) : "";
    }

    async openRecord(id) {
        this.close();
        await this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "cc.mail.thread",
            res_id: id,
            views: [[false, "form"]],
        });
    }

    async openFullCenter() {
        this.close();
        await this.action.doAction(
            "codestra_klyrow_smtp.action_crm_email_center"
        );
    }
}

registry.category("systray").add(
    "codestra_klyrow_smtp.crm_email_center",
    { Component: CodestraCrmEmailCenterPopout },
    { sequence: 21 }
);
