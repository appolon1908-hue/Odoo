# Rollback

Before delivery, cancel the batch and cancel pending outbox records. After
delivery, stop all publication kill switches and suppress/deactivate only
uncalled eligible records through middleware. Never delete attempted VICIdial
leads, calls, dispositions, acknowledgements, CRM records, audit records or
reconciliation evidence.

For a code rollback, stop Odoo, restore the pre-upgrade database and matching
filestore, restore the prior addon source, then start Odoo and verify registry
health. Uninstalling is not a safe substitute after data has been created.
