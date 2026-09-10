# Codestra CRM night theme rollout

## Scope

Install `codestra_workspace_theme` from a reviewed GitHub commit. This is a
backend-only asset addon, independent of the existing public login module.
It adds no models, account provisioning, routes, SSO or permission changes.

The production target is the existing `codestra-odoo-1` service and the
`codestra_odoo` database serving `https://crm.codestra.agency`. Do not deploy a
second public Odoo service or substitute a frontend mockup for the application.

## Gates

1. Required PR checks and the repository's required review must pass on the
   exact candidate before merging. A source check alone is insufficient.
2. Install and upgrade only this addon in isolated Odoo 19/PostgreSQL. Its two
   HTTP tests must pass, including compiled CSS and public login isolation.
3. Complete the authenticated desktop/mobile visual acceptance in
   `design-qa.md`. HTTP checks do not certify button contrast, layout or menu
   reachability. The current cloud browser cannot open the CRM page.
4. Capture and verify a consistent database/filestore recovery pair immediately
   before the production module installation. Preserve the running service's
   Compose configuration and code release identities.

## Prepared Compose overlay

`deploy/compose/compose.workspace-theme.production.yaml` adds one read-only
mount. Set `CODESTRA_WORKSPACE_RELEASE` to the immutable release's
`custom-addons` directory, containing only `codestra_workspace_theme`.
Its source must match the reviewed commit exactly.

Append the overlay to the running service's current Compose file list. Preserve
all existing environment interpolation values privately. Render configuration
without printing secret-bearing environment or credential contents. Compare it
with the running service and confirm image identity, ports, networks, secrets,
volumes, healthcheck and service settings are preserved. The only intended
changes are the new addon mount/search path and the previously reviewed final
`/mnt/extra-addons` fallback. Existing addon precedence must remain unchanged.

After the gates pass, install only `codestra_workspace_theme` with cron, workers
and HTTP disabled in the one-off install process. Recreate only the Odoo service
using the complete reviewed Compose file list, with no dependency restart,
image build or pull. Never use `-u all` for a theme installation.

Verify the container health, root-to-login redirect, existing Codestra login,
authenticated theme bundle and the visual acceptance states. Record the source
SHA, backup paths/checksums, module version, affected service and result. Ask
users to reload existing tabs after the new asset URL has been generated.

## Rollback

Uninstall this presentation-only addon through Odoo's normal module operation
while its source remains mounted, then restore the preceding Compose file list
and recreate only Odoo. Verify the previous styling and login. Keep the paired
backup for recovery; restoring a database is a separate operation that can lose
newer writes and must be planned against the current production state.

## Current status

PR #101 merged with final-head approval and all required checks passing. The
user explicitly approved the live rollout after disclosure of the unavailable
visual browser check. The theme was installed on 2026-09-10; authenticated visual
acceptance remains unverified. See `CRM-NIGHT-LIVE-20260910.md` and
`deploy/evidence/crm-night-live-20260910.json` for installation, backup, served
asset verification and the accompanying call-popup RPC compatibility repair.
