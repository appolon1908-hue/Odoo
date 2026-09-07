/** @odoo-module **/

import { describe, expect, test } from "@odoo/hoot";
import { codestraSessionExpiredHandler } from "@codestra_orbit_theme/js/session_expired";

describe("Codestra Orbit session handling", () => {
    test("registers an RPC response listener", () => {
        let eventName;
        codestraSessionExpiredHandler({ bus: { addEventListener: (name) => { eventName = name; } } });
        expect(eventName).toBe("RPC:RESPONSE");
    });
});
