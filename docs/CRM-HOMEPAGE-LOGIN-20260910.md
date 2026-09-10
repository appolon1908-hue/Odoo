# CRM homepage login activation — 10 September 2026

The CRM root address, <https://crm.codestra.agency/>, now sends signed-out
visitors to the black Codestra login. Previously the branding was available at
`/web/login`, while `/` still served Odoo's default website homepage.

Only the selected CRM website's `homepage_url` setting changed, from unset to
`/odoo`, through the Odoo ORM. Odoo's native entry controller performs the
session check and sends anonymous visitors to `/web/login`; staff and external
users retain Odoo's existing access checks. The selected website is ID 1, the
sole website in `codestra_odoo`; its domain value was left unchanged.

The applied setting is tracked in
[`config/crm-login-entry.production.json`](../config/crm-login-entry.production.json).
This file records the setting; application uses the existing Website settings
interface or Odoo ORM. No new controller or theme installation is required for
this native entry route. Orbit's optional `/codestra/workspace` route remains
a separate installation described in `LOGIN-ENTRY-REPAIR.md`.

At 16:44:02 UTC, a fresh anonymous HTTPS request to `/` returned HTTP 303 to
`/web/login?redirect=%2Fodoo%3F`, followed by HTTP 200. Both the root entry and
direct `/web/login` rendered the Codestra shell and compiled dark CSS, with
the native POST form, password input, and CSRF field. The vendor footer and
database-manager link were absent. Odoo remained healthy throughout.

There was no container restart, schema change, authentication-backend change,
or credential update. A successful human sign-in was not tested.

The previous setting and the verification result are retained in the restricted
operator record `login-homepage-20260910T164312Z`. Rollback is limited to restoring
website 1's prior `homepage_url` value (`False`) through the Odoo ORM and
propagating the normal registry cache invalidation. The website pages and
branding module remain intact.

[Machine-readable verification](../deploy/evidence/crm-root-login-20260910.json)
records the observed redirect and page checks without credentials or session
values.
