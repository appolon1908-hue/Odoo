# Rollback

This branch is staging-only and does not publish scripts or dispositions to an
external system.

To roll back before merge, remove this stacked branch from the test database and
return to `feat/cc-vicidial-mapping`. Do not delete adopted legacy script or
disposition records: canonical wrappers use restrictive links and their evidence
is intentionally retained.

For a database where the upgraded module was installed, restore the disposable
pre-upgrade snapshot or upgrade forward with a reviewed migration. The module is
not declared uninstall-safe. No live flag, middleware writer, VICIdial database,
or production campaign requires reversal because this branch never enables one.
