# Migration policy

`codestra_cc_core` uses non-destructive, idempotent adoption. Canonical business
units and campaigns delegate their legacy owners through unique one-to-one foreign
keys, and canonical channels reference existing mapping rows. The module never
renames or deletes a legacy identifier during adoption.

The data loader reconciles existing records on install and upgrade. Model-level
create hooks reconcile compatible legacy records created after module loading.
Future schema changes must increment the module version and add a versioned
migration when stored values or constraints need transformation.

Every upgrade migration must:

- run in an Odoo transaction;
- preserve legacy history and stable UUIDs;
- keep all live and production flags false;
- be idempotent and restartable;
- classify noncanonical identifiers as blocked exceptions rather than renaming;
- support a database-backup rollback rehearsal; and
- include focused upgrade tests plus full clean-install regression evidence.
