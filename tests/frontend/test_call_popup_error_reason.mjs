import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import vm from "node:vm";

// Exercises the reviewed module source, not the deploy hotfix snapshot.
const source = await readFile(
    new URL("../../custom-addons/codestra_vicidial_crm/static/src/js/call_popup.js", import.meta.url),
    "utf8"
);

// Shape produced by @web/core/network/rpc makeErrorFromResponse(): the server's
// JSON-RPC envelope always carries the literal "Odoo Server Error" at the top
// level and the real exception text under data.message.
function odooRpcError(dataMessage) {
    const error = new Error("Odoo Server Error");
    error.name = "RPC_ERROR";
    error.code = 200;
    error.data = { name: "odoo.exceptions.AccessError", message: dataMessage };
    return error;
}

async function popupHarness(failures = {}) {
    const startup = [];
    const requests = [];
    const services = {
        bus_service: { addEventListener() {} },
        action: { doAction() {} },
        notification: { add() {} },
    };
    const context = vm.createContext({ Set, crypto: { randomUUID: () => "test-id" } });
    const imports = {
        "@odoo/owl": {
            Component: class {},
            onWillStart: (callback) => startup.push(callback),
            useState: (state) => state,
        },
        "@web/core/network/rpc": {
            rpc: async (route, params) => {
                requests.push({ route, params });
                if (failures[route]) throw failures[route];
                return null;
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
    popup.setup();
    return { popup, startup, requests };
}

test("dial-pad readiness failure shows the server's reason, not the generic label", async () => {
    const reason = "Agent is not mapped to an active telephony identity.";
    const { popup, startup } = await popupHarness({
        "/codestra/call-control/v1/dialpad": odooRpcError(reason),
    });
    await assert.doesNotReject(startup[0]);
    assert.equal(popup.ui.dialpad.enabled, false);
    assert.equal(popup.ui.dialpad.status, "Unavailable");
    assert.equal(popup.ui.dialpad.reason, reason);
    assert.notEqual(popup.ui.dialpad.reason, "Odoo Server Error");
});

test("number lookup failure shows the server's reason", async () => {
    const reason = "Dialer requires one exact CRM contact or lead match.";
    const { popup } = await popupHarness({
        "/codestra/call-control/v1/match": odooRpcError(reason),
    });
    popup.ui.dialpad.number = "+18496582053";
    const result = await popup.resolveDialpad();
    assert.equal(result, null);
    assert.equal(popup.ui.dialpad.error, reason);
});

test("current-call startup failure shows the server's reason", async () => {
    const reason = "Agent tenant binding is invalid.";
    const { popup, startup } = await popupHarness({
        "/codestra/call-control/v1/current": odooRpcError(reason),
    });
    await assert.doesNotReject(startup[0]);
    assert.equal(popup.ui.error, reason);
});

test("a bare transport error still falls back to its own message", async () => {
    const { popup, startup } = await popupHarness({
        "/codestra/call-control/v1/dialpad": new Error("Phone unavailable"),
    });
    await assert.doesNotReject(startup[0]);
    assert.equal(popup.ui.dialpad.reason, "Phone unavailable");
});

test("an error with no message at all uses the widget fallback", async () => {
    const empty = new Error("");
    empty.data = {};
    const { popup, startup } = await popupHarness({
        "/codestra/call-control/v1/dialpad": empty,
    });
    await assert.doesNotReject(startup[0]);
    assert.equal(popup.ui.dialpad.reason, "Dialer is unavailable.");
});
