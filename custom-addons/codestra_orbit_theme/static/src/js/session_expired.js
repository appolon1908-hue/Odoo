/** @odoo-module **/

import { registry } from "@web/core/registry";

export function codestraSessionExpiredHandler(env) {
    env.bus.addEventListener("RPC:RESPONSE", (event) => {
        if (event.detail?.data?.error?.data?.name === "odoo.http.SessionExpiredException") {
            const redirect = encodeURIComponent(window.location.pathname + window.location.search);
            window.location.assign(`/web/login?session_expired=1&redirect=${redirect}`);
        }
    });
}

registry.category("services").add("codestra_orbit_session_expired", {
    dependencies: [],
    start(env) {
        codestraSessionExpiredHandler(env);
        return {};
    },
});
