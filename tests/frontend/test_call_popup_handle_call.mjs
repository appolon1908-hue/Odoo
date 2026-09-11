import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import vm from "node:vm";

const source = await readFile(
    new URL("../../custom-addons/codestra_vicidial_crm/static/src/js/call_popup.js", import.meta.url),
    "utf8"
);

async function popupHarness(routeHandlers = {}) {
    const requests = [];
    const startup = [];
    const services = {
        bus_service: { addEventListener() {}, removeEventListener() {} },
        action: { doAction() {} },
        notification: { add() {} },
    };
    const context = vm.createContext({ Set, crypto: { randomUUID: () => "test-id" }, navigator: {} });
    const imports = {
        "@odoo/owl": {
            Component: class {},
            onWillStart: (callback) => startup.push(callback),
            onWillDestroy: () => {},
            useState: (state) => state,
        },
        // PR #102 wires the canonical realtime client into the popup. The harness
        // never returns an enabled boot payload, so it is only imported, not run.
        "./calling_realtime": {
            CallingRealtimeClient: class {
                connect() {}
                stop() {}
            },
        },
        "@web/core/network/rpc": {
            rpc: async (route, params) => {
                requests.push({ route, params });
                const handler = routeHandlers[route];
                if (!handler) return null;
                const result = handler(params);
                if (result instanceof Error) throw result;
                return result;
            },
        },
        "@web/core/registry": { registry: { category: () => ({ add() {} }) } },
        "@web/core/utils/hooks": {
            useService: (name) => {
                if (!(name in services)) throw new Error(`Service ${name} is not available`);
                return services[name];
            },
        },
    };
    const module = new vm.SourceTextModule(source, { context });
    await module.link((specifier) => {
        const exports = imports[specifier];
        assert.ok(exports, `Unexpected dependency: ${specifier}`);
        return new vm.SyntheticModule(Object.keys(exports), function () {
            for (const [name, value] of Object.entries(exports)) this.setExport(name, value);
        }, { context });
    });
    await module.evaluate();
    const popup = new module.namespace.CodestraCallPopup();
    await popup.setup();
    return { popup, requests };
}

function accessError(message) {
    const error = new Error("Odoo Server Error");
    error.data = { name: "odoo.exceptions.AccessError", message };
    return error;
}

test("a two-way call event does not reject when the reverse-match lookup fails", async () => {
    const { popup } = await popupHarness({
        "/codestra/call-control/v1/match": () =>
            accessError("Agent tenant binding is invalid."),
    });
    await assert.doesNotReject(() =>
        popup.handleCall({ call_id: "call-1", state: "connected", caller_number: "+15551234567" })
    );
    assert.equal(popup.ui.error, "Agent tenant binding is invalid.");
    assert.equal(popup.ui.call.call_id, "call-1");
});

test("a two-way call event does not reject when the history lookup fails", async () => {
    const { popup } = await popupHarness({
        "/codestra/call-control/v1/calls/call-2/history": () =>
            accessError("The call is not assigned to the current agent."),
    });
    await assert.doesNotReject(() =>
        popup.handleCall({ call_id: "call-2", state: "connected", customer: { id: 9 } })
    );
    assert.equal(popup.ui.error, "The call is not assigned to the current agent.");
});

test("the friendly exception message is preferred over the generic RPC wrapper text", async () => {
    const { popup } = await popupHarness({
        "/codestra/call-control/v1/match": () => accessError("Agent is not mapped to an active telephony identity."),
    });
    await popup.handleCall({ call_id: "call-3", state: "ringing", caller_number: "+15557654321" });
    assert.equal(popup.ui.error, "Agent is not mapped to an active telephony identity.");
    assert.notEqual(popup.ui.error, "Odoo Server Error");
});

test("a successful two-way call event still populates history and clears any prior error", async () => {
    const { popup } = await popupHarness({
        "/codestra/call-control/v1/calls/call-4/history": () => ({ items: [{ id: 1 }] }),
    });
    popup.ui.error = "stale error from a previous event";
    await popup.handleCall({ call_id: "call-4", state: "connected", customer: { id: 3 } });
    assert.equal(popup.ui.error, "");
    assert.deepEqual(popup.ui.history, [{ id: 1 }]);
});
