# Staging migration execution

Run module installation and upgrades only against a sanitized isolated restore. Capture the pre-upgrade backup identity, source and target module versions, migration checksums, before/after counts, duplicate preflight, interrupted-upgrade restart, query plans, elapsed time, and restoration result.

Never delete records to make an upgrade pass. A failed migration closes the staging gate and requires restoration through the reviewed procedure.
