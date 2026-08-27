# Rollback

Before deployment, back up the Odoo database and record the prior addon SHA.
If rollback is required, disable menus and playback, restore the prior reviewed
source revision, and run an approved module upgrade. Preserve recording
metadata, idempotency rows, retention audits and playback audits. Do not unlink
recording references or delete object-storage versions. Module uninstall is a
CI safety check, not permission to uninstall production.
