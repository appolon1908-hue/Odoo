# Codestra Appointments

Odoo 19 add-on for governed appointment, callback, reminder, and scheduler
workflows. It extends the canonical `codestra.callback` model owned by
`codestra_vicidial_crm` so appointment-originated and VICIdial-originated
callbacks share one table without conflating Odoo campaign desired state with
the physical VICIdial campaign reference.

Callback creation is idempotent per business unit, supports agent or team
ownership, preserves timezone-aware scheduling data, records lifecycle history,
and keeps middleware synchronization disabled unless explicitly configured.
The upgrade migrations are restartable and reconcile prior duplicate-model
installations without deleting callback records.
