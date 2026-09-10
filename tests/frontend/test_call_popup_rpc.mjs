import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import vm from "node:vm";

const source = await readFile(new URL("../../deploy/hotfixes/odoo19-call-popup-rpc/call_popup.js", import.meta.url), "utf8");

async function popupHarness(failTransport = false) {
    const startup = [];
    const requests = [];
    const requestedServices = [];
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
                if (failTransport) throw new Error("Phone unavailable");
                return null;
            },
        },
        "@web/core/registry": { registry: { category: () => ({ add() {} }) } },
        "@web/core/utils/hooks": {
            useService: (name) => {
                requestedServices.push(name);
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
    return { popup, startup, requests, requestedServices };
}

test("Odoo 19 popup starts without a registered rpc service", async () => {
    const { popup, startup, requests, requestedServices } = await popupHarness();
    assert.equal(startup.length, 1);
    await startup[0]();
    assert.deepEqual(requestedServices, ["bus_service", "action", "notification"]);
    assert.equal(requests.length, 1);
    assert.equal(requests[0].route, "/codestra/call-control/v1/current");
    assert.equal(popup.ui.call, null);
    assert.equal(popup.ui.error, "");
});

test("a phone transport failure does not reject workspace startup", async () => {
    const { popup, startup, requests } = await popupHarness(true);
    await assert.doesNotReject(startup[0]);
    assert.equal(popup.ui.error, "Phone unavailable");
    assert.equal(requests.length, 1);
});
