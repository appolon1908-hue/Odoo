# Codestra CRM login and workspace entry

The intended login design already lives in `codestra_login_branding`: a
responsive black-and-gold shell with local assets, a native Odoo login form,
password recovery, keyboard focus and reduced-motion support. Orbit supplies
Keycloak SSO and workspace styling. It now depends on that login shell and
renders one SSO button without duplicating the card heading. The Codestra
provider is excluded from Odoo's generic implicit-flow links; other OAuth
providers remain available.

## Production observation, 2026-09-10

Read-only checks on Server A and the public CRM host found:

- `/` returns HTTP 200 with `Home | My Website`, no login form and no Codestra shell.
- `/web/login` returns HTTP 200 with the native login form, but no Codestra shell.
- The production database has `website` installed and `auth_oauth` uninstalled.
  Neither Codestra login module appears in its module registry.
- Website 1 has no configured domain or homepage URL.

The supplied screenshot shows the default website homepage while already signed
in. It is not a screenshot of the repository's custom login design.

## Activation

Use the existing protected release process in `ORBIT-THEME-SSO-RELEASE.md` and
`LOGIN-ADMIN-DATABASE-RUNBOOK.md`, including a matching database/filestore recovery
point. Publish and install the accepted addon version on isolated staging first.
Install `codestra_orbit_theme`; its dependency installs `codestra_login_branding`.
For an existing installation, upgrade both modules so their views and frontend
assets match the accepted source.

On the selected CRM website only, record the previous `homepage_url` and set it
to `/codestra/workspace` through the existing Odoo Website configuration process.
Do not update every website or overwrite website pages. Verify the website ID
and domain for the target environment before applying the setting.

| Session at the CRM homepage | Destination |
| --- | --- |
| Signed out | `/web/login?redirect=%2Fodoo` |
| Internal Odoo user | `/odoo` |
| Portal user | `/my` |

The route chooses a fixed destination from the authenticated Odoo user type. It
does not accept a caller-selected destination, grant roles, change passwords,
or alter campaign/company access. Direct `/web/login` remains available for
recovery. SSO appears only when its provider is enabled and the issuer/client ID
are configured; enabling SSO remains a separate identity configuration step.

## Verification and rollback

The Odoo HTTP tests cover native CSRF/password fields, one branded shell and
heading, one Codestra code-flow button, public/staff/portal entry, the configured
homepage, and preservation of unconfigured websites. Existing login tests load
the production CSS bundle. Repository CI also tests all addons and upgrades on
Odoo 19/PostgreSQL.

Before production acceptance, verify desktop and mobile rendering, password
recovery, local login, enabled Keycloak login, logout, and each session route on
the exact staging release. Source or disposable test results alone do not prove
production activation.

To roll back the homepage, restore the recorded `homepage_url`. For a module
rollback, use the previous accepted release and paired database/filestore
recovery point according to the release runbook. Retain native local login.

## Repair validation, 2026-09-10

`bash scripts/run_ci.sh` passed. A disposable, internally networked Odoo 19 /
PostgreSQL fixture installed only `codestra_orbit_theme` explicitly and resolved
`codestra_login_branding` as its dependency. Tagged HTTP/view tests passed with
zero failures or errors, including the production frontend CSS bundle. Upgrading
both modules also passed. The fixture containers, network and volume were removed.
The production database, addon mounts and homepage configuration were unchanged.

The cloud browser could not load the public CRM page, so no live visual acceptance
is claimed. The in-conversation design preview illustrates the recovered layout;
it is not a production screenshot or an authenticated sign-in test.
