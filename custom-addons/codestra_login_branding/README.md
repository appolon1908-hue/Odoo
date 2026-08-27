# Codestra Login Branding

Odoo 19 authentication-page branding for Codestra CRM.

## Scope

- inherits `web.login_layout` rather than editing Odoo core files;
- preserves Odoo's login form action, CSRF token, field names, password behavior,
  autocomplete attributes, OAuth insertion point, reset-password inheritance,
  and database selection when multiple databases are legitimately exposed;
- replaces the default 300px card with a responsive Codestra shell;
- removes the database-manager and “Powered by Odoo” footer from the login
  surface;
- uses local assets only—no remote fonts, trackers, scripts, or images;
- includes Odoo view and HTTP rendering tests.

## Installation

```bash
odoo -d <database> -i codestra_login_branding --stop-after-init --no-http
```

For upgrades:

```bash
odoo -d <database> -u codestra_login_branding --stop-after-init --no-http
```

Use the reviewed exact commit in staging first. The module does not create users,
change passwords, change database configuration, or activate any external
integration.
