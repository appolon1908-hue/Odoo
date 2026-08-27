# CC-01 — Core, Reliability, and Audit Baseline

This branch joins the governed call-center mission foundation with the separately reviewed canonical Odoo 19 addon import. The merge preserves the existing Odoo module history and adds mission-level compatibility modules rather than copying or renaming working data models.

## Included

- the canonical Codestra addon set already reviewed on `feat/import-canonical-odoo-modules`;
- `codestra_cc_core` compatibility ownership facade;
- `codestra_cc_reliability` compatibility ownership facade;
- `codestra_cc_audit` compatibility ownership facade;
- a machine-readable module coverage and gap registry;
- dependency tests proving the audited implementation modules are installed with each facade.

## Safety state

```text
LIVE_ODOO_WRITE=false
ENABLE_EXTERNAL_DELIVERY=false
EMAIL_DELIVERY=false
SMS_DELIVERY=false
CALLBACK_DISPATCH=false
PSTN_DIALING=false
N8N_ACTIVATION=false
DATABASE_MIGRATED=NO
RUNTIME_DEPLOYED=NO
```

This is a source integration branch. It does not install or upgrade modules on the live Odoo host.
