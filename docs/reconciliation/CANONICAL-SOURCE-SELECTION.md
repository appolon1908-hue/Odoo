# Canonical source selection

## Repository anchors

- Mission-start and current `main`: `35d87740ac76458e3652b7d71ba2a2a6da2d8893`
- Verified WFM/reporting checkpoint: `a2592e66ab0b3953548b3b55735a852857ed892d`
- Selected source candidate: `4681d755039ee7f4fec21228bac234a668541de8` (`feat/cc-compliance-audit`)

The WFM/reporting checkpoint is 78 commits ahead of `main`, contains 67 custom-addon directories, 19 migration Python files, 15 controller implementation files, and 96 Odoo test files. Its retained CI evidence reports 435 tests with zero failures or errors.

The compliance/audit branch is a direct 10-commit descendant. It retains the same 67 modules and 19 migration files while adding append-only audit, compliance, payment-safety, retention, ACL, record-rule, and negative-test work. Its current GitHub runtime check is successful. Because the mission permits security correction during the feature freeze, this descendant is the selected reconstruction source.

## Classification of later work

| Change family | Decision | Reason |
|---|---|---|
| Compliance and append-only audit through `4681d755…` | `INCLUDE_NOW` | Security and compliance correction; same module count; successful runtime CI |
| Moy, Codestra Services, Senior Products, MoneyBee, RLP, For the People, TradeX, Calderon overlays | `PORT_LATER` | New business-unit feature work prohibited by the freeze |
| Cross-campaign certification and production-gate evidence | `PORT_LATER` | Evidence/tooling may be reconstructed after the 67-module source is canonical; do not copy stale branch-stack governance |
| Controlled catalog and complete 77-module bundle | `PORT_LATER` | Adds ten modules and business data beyond the approved 67-module boundary |
| Separate MoneyBee account-sync/receipt PRs | `BLOCKED` | Require ownership and live-drift reconciliation before selective port |
| Scraper projection PR | `BLOCKED` | Current PR CI is failing and provider execution belongs to Middleware |
| n8n contract documents | `PORT_LATER` | Documentation-only; n8n remains orchestration-only |

## Candidate measurements

```text
CANDIDATE_SHA=4681d755039ee7f4fec21228bac234a668541de8
MODULE_COUNT=67
TEST_FILE_COUNT=98
MIGRATION_PY_COUNT=19
CONTROLLER_IMPLEMENTATION_FILE_COUNT=15
EXTERNAL_ROUTE_COUNT=71
SECURITY_FILE_COUNT=92
```

Counts describe source inventory, not business certification. The last retained exact runtime count at the WFM checkpoint is 435. The compliance descendant must produce a new exact test count on this reconciliation branch.

## Blocking reconciliation findings

The selected tree is a source candidate, not yet a release candidate:

- resource controllers using `auth="none"` require service-auth and scope verification;
- direct outbound HTTP execution exists in several addons and must be reconciled against the Middleware-only connector rule;
- legacy event/callback ownership and compatibility layers require live installed-module evidence;
- current `main` is unprotected;
- no production runtime baseline or server-to-GitHub checksum ledger exists yet;
- fresh-install, deployed-baseline upgrade, interruption, paired restore, contract, and staging gates remain pending.

The reconciliation branch is intentionally based on current `main`; the candidate tree is reconstructed into it without making the stacked feature branch the new base.
