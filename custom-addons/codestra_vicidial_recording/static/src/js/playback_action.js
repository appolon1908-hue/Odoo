/** @odoo-module **/

import { registry } from "@web/core/registry";

async function recordingPlaybackAction(env, action) {
    const url = action.params && action.params.url;
    if (typeof url !== "string" || !url.startsWith("https://")) {
        env.services.notification.add("Invalid recording playback grant.", {
            type: "danger",
        });
        return;
    }
    // Intentionally ephemeral: no ORM, chatter, localStorage or sessionStorage write.
    window.open(url, "_blank", "noopener,noreferrer");
}

registry.category("actions").add(
    "codestra_recording_playback",
    recordingPlaybackAction,
);
