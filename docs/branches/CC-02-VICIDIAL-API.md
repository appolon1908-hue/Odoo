# CC-02 — VICIdial and Canonical API Boundary

This branch adds the `codestra_cc_vicidial` mission facade and records the exact relationship between canonical Kong paths and the existing hardened Odoo controllers.

The implementation reuses signed event ingestion, idempotent event storage, tenant and campaign binding, normalized phone matching, agent workspace, mandatory disposition, click-to-call command records, transfer allowlists, protected recording references, and reconciliation already present in the canonical modules.

## Remaining certification work

- deploy the Kong route rewrite in isolated staging;
- prove Keycloak audience and scope enforcement at ingress;
- run exact replay, altered-body replay, out-of-order event, cross-tenant, and browser authorization tests;
- measure screen-pop database lookup and end-to-end p95;
- keep call control and PSTN dialing disabled during read-only certification.

```text
VICIDIAL_DATABASE_WRITES=DISALLOWED
LIVE_CALL_CONTROL=false
PSTN_DIALING=false
RUNTIME_DEPLOYED=NO
```
