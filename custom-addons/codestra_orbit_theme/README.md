# Codestra Orbit Theme and SSO

Supported Odoo 19 addon for the Codestra operator experience. It does not patch
or copy Odoo core.

## Capabilities

- responsive Codestra login, logout confirmation, and session-expiry handling;
- Keycloak authorization-code SSO with server-bound, expiring state;
- no access or identity token in browser storage;
- shared website and portal shell styling;
- backend navigation and workspace styling;
- semantic CSS tokens and keyboard-visible focus states.

The addon deliberately defines no business model, ACL, or record rule. Existing
Odoo and Codestra authorization and company isolation remain authoritative.

## Configuration

Create a confidential Keycloak client with the exact callback
`https://crm.codestra.agency/codestra/sso/callback` and post-logout redirect
`https://crm.codestra.agency/web/login*`. In **Settings → Codestra Orbit**, set
the HTTPS realm issuer, client ID, and client secret. Enable the generated
Codestra OAuth provider only after staging redirect/read-back checks pass.

Do not commit credentials. Supply the client secret through the protected
runtime configuration process.

## Install and upgrade

```bash
odoo -d <isolated-staging-db> -i codestra_orbit_theme --stop-after-init --no-http
odoo -d <isolated-staging-db> -u codestra_orbit_theme --stop-after-init --no-http
```

Run the complete repository checks with `bash scripts/run_ci.sh`, then run the
tagged Odoo tests in the isolated runtime. Production promotion must use the
same accepted SHA and image digest.
