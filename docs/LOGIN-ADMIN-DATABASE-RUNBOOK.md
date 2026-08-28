# Codestra Odoo login, administrator, database, and module runbook

## Scope and safety

This change adds a non-secret login module and operational checks. It does not
contain a password, database credential, PostgreSQL dump, filestore, or live
server configuration.

Odoo user ID `1` (`base.user_root`) is the technical superuser and must not be
converted into a human login. The designated account
`appolon1908@gmail.com` is provisioned as the human Odoo Administrator through
`base.group_system`. It is not a PostgreSQL superuser.

## 1. Review the repository

Run the static, fail-closed review:

```bash
bash scripts/run_ci.sh
```

The pipeline validates every custom module, the inherited login views, local
assets, administrator policy, secret-free bootstrap, database audit contract,
and the Middleware-only Odoo write boundary.

GitHub Actions additionally runs:

```bash
bash scripts/run_odoo_module_tests.sh
```

That runtime job starts isolated Odoo 19 and PostgreSQL containers from
digest-pinned official images, installs every custom module, runs its Odoo
tests, provisions the designated administrator with a generated CI-only secret,
and audits the resulting database state. It does not connect to or prove the
health of staging or production.

## 2. Stage the login module

Deploy an exact reviewed commit to staging and mount `custom-addons/` read-only
at the discovered Odoo extra-addons path.

For a first installation:

```bash
odoo \
  -d <staging_database> \
  -i codestra_login_branding \
  --stop-after-init \
  --no-http
```

For a reviewed upgrade:

```bash
odoo \
  -d <staging_database> \
  -u codestra_login_branding \
  --stop-after-init \
  --no-http
```

Restart only the Odoo service. Load `/web/login` in a private browser window
and verify desktop and mobile layouts, login errors, password visibility,
reset-password/OAuth links when installed, and successful login.

## 3. Provision the designated administrator

Generate the password outside Git and mount it into the Odoo container or
restricted operator environment as a file readable only by the Odoo runtime
user. The reviewed minimum is 24 characters.

Run a dry run first:

```bash
docker exec -i \
  -e ODOO_ADMIN_LOGIN=appolon1908@gmail.com \
  <odoo_container> \
  odoo shell -d <database> --no-http \
  < scripts/ensure_codestra_admin.py
```

Apply only after the dry-run target is correct:

```bash
docker exec -i \
  -e ODOO_ADMIN_LOGIN=appolon1908@gmail.com \
  -e ODOO_ADMIN_BOOTSTRAP_APPLY=YES \
  -e ODOO_ADMIN_PASSWORD_FILE=/run/secrets/codestra_odoo_admin_password \
  <odoo_container> \
  odoo shell -d <database> --no-http \
  < scripts/ensure_codestra_admin.py
```

The script:

- refuses duplicate matching accounts;
- refuses to repurpose `base.user_root`;
- removes portal/public user-type groups;
- assigns `base.group_system`;
- keeps the default company inside the account's allowed companies;
- requires an externally mounted private password file;
- commits only behind the exact apply gate;
- verifies the resulting account before committing.

## 4. Audit the live database and every module

Run this read-only audit on the actual host:

```bash
sudo bash scripts/audit_odoo_runtime.sh \
  --odoo-container <odoo_container> \
  --db-container <postgres_container> \
  --database <database> \
  --base-url https://<odoo-hostname>
```

A passing audit proves, at the time it runs:

- both containers are running and not unhealthy;
- PostgreSQL accepts the target database;
- the expected Odoo tables exist;
- Odoo can load the database registry;
- `base` and `web` are installed;
- no modules are waiting to install, upgrade, or remove;
- every module found under `custom-addons/` is installed;
- exactly one active login matches `appolon1908@gmail.com`;
- that account belongs to `base.group_system`;
- the public login route responds successfully.

Save the complete output as deployment evidence. Do not represent GitHub CI as
proof that this live-host check passed.

## 5. Production gate

Before production:

1. create a matching PostgreSQL backup and filestore recovery point;
2. verify restoration in an isolated environment;
3. deploy the same reviewed commit already accepted in staging;
4. upgrade only `codestra_login_branding`;
5. run the live runtime audit;
6. verify login with the designated administrator;
7. retain the previous exact commit and recovery point for rollback.

Do not run `-u all`, edit files inside a running container, store the
administrator password in GitHub/Compose/shell history, or grant the human
Odoo administrator PostgreSQL superuser access.
