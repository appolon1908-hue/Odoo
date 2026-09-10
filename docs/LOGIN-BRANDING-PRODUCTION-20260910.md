# Codestra black login deployment — 10 September 2026

The black-and-gold Codestra login is serving at
<https://crm.codestra.agency/web/login>. The production check at
16:15:53 UTC returned HTTP 200 with the Codestra shell and compiled dark CSS.

## Change

Installed only `codestra_login_branding` version `19.0.1.0.1` from reviewed
source commit `3396700f9e24c58b71cbe1733cd65e396d11d002`. The audited
[Compose overlay](../deploy/compose/compose.login-branding.production.yaml)
adds an immutable, read-only module directory to the existing add-ons path.
The existing Odoo image, worker settings, database connection, integrations,
and runtime mounts were preserved. The overlay explicitly retains the existing
`/mnt/extra-addons` mount, which was absent from the rendered base file list.

The PR review follow-up appends `/mnt/extra-addons` to the search path, after
the pinned release directories. A read-only production inventory found all
95 installed modules in the existing search path, with 24 duplicate module
names in the retained directory and none available only there. Appending the
directory preserves current module precedence while making the retained
mount discoverable. The evidence below records the original deployment;
application of this review follow-up is recorded separately in the PR.

This is a targeted module deployment on the existing Odoo 19 runtime. The
evidence covers the login surface and its recovery rehearsal.

The native POST login form, password input, and CSRF field remain present.
The vendor footer and database-manager link are absent. The served stylesheet
comes from the same origin and contains the Codestra dark palette.

## Validation

- Repository checks passed, including 129 source tests.
- A matched production database and filestore backup was restored into a
  temporary PostgreSQL 17/Odoo 19 instance on an internal Docker network.
  Scheduled jobs were disabled in the restored database.
- All 346 restored attachment references had matching files and checksums.
- Installation, upgrade, and restart succeeded in that restored instance.
- All three module view/HTTP tests passed, including website compatibility
  and retrieval of the compiled frontend CSS: zero failures and zero errors.
- The production container is healthy, and the live login/CSS checks passed.
- The reviewed read-only Odoo audit passed with
  `EXPECTED_ODOO_MODULES=codestra_login_branding`; the registry loaded, required
  modules were installed, and no pending module transitions were reported.
- The existing designated administrator identity and Administrator group
  membership passed the audit. No account provisioning or password change
  was performed.

The cloud browser could not reach this site, so desktop/mobile visual
acceptance and a successful human sign-in remain unverified. The public HTTPS
checks used certificate validation from the production host.

## Recovery and operational record

Recovery ID: `20260910T160416Z`. A second matched backup was captured immediately
before installation. Both encrypted local recovery archives were read back
successfully; their database and filestore contents matched the recorded
checksums. Plaintext working copies and the temporary test containers, database
volume, credentials, filestore, and internal network were removed afterward.

Odoo was paused for 8.84 seconds to capture the rehearsal pair and 15.79 seconds
for the immediate backup, targeted installation, and service recreation.

An additional Restic copy was not made: the configured repository returned
`Access Denied`. The verified encrypted recovery archives remain on the host.

The restricted operator record retains the original container metadata and
Compose configuration in the encrypted recovery archive. If rollback is
required, stop only Odoo, restore the matching database and filestore pair,
restore the captured previous command and complete mount set, and restart
Odoo. Keep the branding source available until the pre-install database state
has been restored. Do not run `-u all` or change administrator credentials as
part of this rollback.

Administrator provisioning remains a separate operation through
`scripts/ensure_codestra_admin.py`, with its explicit apply gate and external
password-file requirement. The technical superuser and PostgreSQL roles were
not repurposed.

Machine-readable results are in
[the deployment evidence](../deploy/evidence/login-branding-20260910.json).
