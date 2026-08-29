# Rollback

Before deployment, capture the Odoo PostgreSQL database, filestore, installed
module state, and the current addon tree. Stop if any backup is incomplete.

Rollback restores the paired database and filestore snapshot and the previous
read-only addon tree together, then recreates only the Odoo application
container and verifies `/web/health`. Never downgrade only Python/XML source
after a schema-changing module upgrade.

Live PSTN, VICIdial writes, callback dispatch, and live call control must remain
disabled throughout deployment and rollback.
