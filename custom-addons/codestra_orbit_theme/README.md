# Codestra Orbit Theme and SSO

Supported Odoo 19 addon for the Codestra operator experience. It does not patch
or copy Odoo core.

## Capabilities

- the existing black-and-gold Codestra login shell, installed as a dependency;
- one SSO button, local recovery login, logout and session-expiry messages;
- optional website homepage routing for staff and portal users;
- Keycloak authorization-code SSO with server-bound, expiring state;
- no access or identity token in browser storage;
- shared website and portal shell styling;
- backend navigation and workspace styling;
- semantic CSS tokens and keyboard-visible focus states.

The addon deliberately defines no business model, ACL, or record rule. Existing
Odoo and Codestra authorization and company isolation remain authoritative.

## Configuration

Use the reviewed `odoo-web` Keycloak browser client with Authorization Code +
PKCE (S256) and the exact callback
`https://crm.codestra.agency/codestra/sso/callback` and post-logout redirect
`https://crm.codestra.agency/web/login*`. In **Settings → Codestra Orbit**, set
the HTTPS realm issuer and client ID. A client secret is optional for an identity
explicitly configured as confidential; the public PKCE client does not need one.
Enable the generated
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

## CRM entry page

The theme does not replace every website homepage. On the CRM website, set the
existing Website **Homepage URL** to `/codestra/workspace` using the approved
Odoo configuration process after module installation. Other websites keep their
current homepage. The route sends visitors to the branded login, authenticated
staff to `/odoo`, and portal users to `/my`. All three destinations retain normal
Odoo authentication and access checks.

See `docs/LOGIN-ENTRY-REPAIR.md` for the observed production gap, verification,
and rollback. Installing the theme does not enable or configure Keycloak SSO.
