# Odoo 19 call popup runtime repair

The production integration release `91e22ef4e69e624142bb3865b16c43a14e8b69d6`
still requested `useService("rpc")`. In Odoo 19, RPC is imported from
`@web/core/network/rpc`; it is not a registered service. This caused the popup's
`setup()` to throw and interrupt the authenticated web client.

This snapshot changes only the RPC import and assignment in the deployed file.
The same compatibility fix already exists in the reviewed application source at
`cc87205e4a71a6f9af872ddaca2943bbb1e9b2b9`. Other newer call-result and rematching
behavior is deliberately left for its full module rollout with matching server
controllers. No calling, matching, callback or dispatch behavior is changed.

Mount this file read only over the resolved production asset path:
`/mnt/integration-addons/codestra_vicidial_crm/static/src/js/call_popup.js`.
The original immutable integration release remains untouched. Recreate only the
Odoo service, regenerate/check its backend asset bundle, and reload open tabs.
Rollback removes the file mount and recreates Odoo with its preceding Compose
file list. No business-schema migration is required.

Run the focused regression test with:
`node --experimental-vm-modules --test tests/frontend/test_call_popup_rpc.mjs`.
It executes the actual popup setup against an Odoo 19 service map without an
RPC service, then exercises the registered startup callback with a mocked RPC
transport. It does not place calls or contact a live endpoint.
