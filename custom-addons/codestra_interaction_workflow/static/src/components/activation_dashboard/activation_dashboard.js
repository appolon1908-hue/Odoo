/** @odoo-module **/
import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class ActivationDashboard extends Component {
    static template = "codestra_interaction_workflow.ActivationDashboard";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({ loading: true, error: null, snapshot: null });
        this.timer = null;
        onWillStart(() => this.loadDashboard());
        onWillUnmount(() => this.timer && clearInterval(this.timer));
    }

    async loadDashboard() {
        this.state.loading = true;
        try {
            this.state.snapshot = await this.orm.call("codestra.integration.dashboard", "get_dashboard_snapshot", [], { window_minutes: 60 });
            this.state.error = null;
            if (!this.timer) this.timer = setInterval(() => this.loadDashboard(), 15000);
        } catch (error) {
            this.state.error = error.message;
            this.notification.add("Integration dashboard unavailable.", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }
}

registry.category("actions").add("codestra_interaction_workflow.activation_dashboard", ActivationDashboard);
