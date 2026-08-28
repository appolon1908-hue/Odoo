# Duplicate model and facade audit

Source: `feat/cc-compliance-audit` at `4681d755039ee7f4fec21228bac234a668541de8`.

A duplicate `_name` is a blocker; ordinary `_inherit` extensions are not duplicate model ownership.

No duplicate `_name` declarations were detected.

## Named facade pairs requiring ownership decisions

| Pair | Classification |
|---|---|
| `call_center_core` / `codestra_cc_core` | `call_center_core=CANONICAL_OWNER`; `codestra_cc_core=FACADE_ONLY` |
| `call_center_campaign` / `codestra_cc_campaign` | `call_center_campaign=CANONICAL_OWNER`; `codestra_cc_campaign=FACADE_ONLY` |
| `call_center_compliance` / `codestra_cc_compliance` | `call_center_compliance=CANONICAL_OWNER`; `codestra_cc_compliance=COMPATIBILITY_LAYER` with separately named evidence/policy models |
| `codestra_vicidial_crm` / `codestra_appointments` / `codestra_cc_calls` | `codestra_vicidial_crm=CANONICAL_OWNER` for `codestra.callback`; the others are `COMPATIBILITY_LAYER` extensions/new scoped operations |
| `codestra_vicidial_crm` / `codestra_integration_hub` | `codestra_vicidial_crm=CANONICAL_OWNER` for the legacy event model; `codestra_integration_hub=MIGRATE_AND_REMOVE` unless live-state reconciliation proves it remains required |
| `codestra_campaign_crm_os` / canonical campaign modules | `MIGRATE_AND_REMOVE` pending live data and migration proof |
