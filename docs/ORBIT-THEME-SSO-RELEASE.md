# Orbit theme and SSO release evidence

This change is a supported addon and does not modify Odoo core. Source review
alone does not certify a live deployment.

## Staging acceptance

Record the exact source SHA, image digest, database and filestore backup IDs,
and test output. Install, restart, then upgrade `codestra_orbit_theme` on an
isolated production-like database. Verify local recovery login, Keycloak login,
callback state rejection, logout at both Odoo and Keycloak, expired-session
re-entry, portal/website shell, backend navigation, keyboard focus, mobile
layout, company switching, cross-company denial, ACLs, record rules, and zero
unexpected external effects.

## Rollback rehearsal

1. Disable the Codestra OAuth provider while retaining local recovery access.
2. Restore the pre-upgrade database and matching filestore backup.
3. Redeploy the previous accepted image digest; never edit the running image.
4. Restart Odoo and verify `/web/health`, local login, portal routes, asset
   compilation, scheduled jobs, company isolation, and audit continuity.
5. Retain checksums and timestamps for the backup, restore, image, and results.

Production is blocked until the repository production evidence validator
accepts the exact staging-certified digest and the protected production
approval is recorded.
