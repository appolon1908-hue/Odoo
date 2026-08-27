# Codestra Base

Shared Odoo 18 foundation for Codestra role groups, reusable metadata mixins, and fail-closed feature flags. It owns no transactional business tables and performs no external connectivity.

The existing `codestra_vicidial_crm` groups and XML IDs remain compatibility-owned by that addon. The new `group_codestra_*` groups are foundation roles; any bridge is deferred to the core-reconciliation phase.

Install and test only in `codestra_odoo_test` during this phase. Roll back by restoring the pre-install test dump and removing the tested source commit; production is not changed.
