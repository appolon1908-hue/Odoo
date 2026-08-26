# Codestra Odoo 19 Custom Addons

This repository is the source of truth for Codestra's self-hosted Odoo 19 custom modules.

> The repository is currently public. Keep it limited to the non-secret bootstrap until its visibility is changed to private. Do not import Codestra business modules or server configuration while it is public.

## Operating model

1. Create a feature branch.
2. Change or add modules under `custom-addons/`.
3. Open a pull request and pass CI.
4. Deploy the reviewed, merged commit SHA to staging.
5. Upgrade only the affected modules and run smoke tests.
6. Deploy the exact same commit SHA to production after backup and approval.

## Repository scope

Commit:

- custom Odoo modules;
- module tests and migration scripts;
- non-secret configuration templates;
- validation and deployment scripts;
- operational documentation.

Never commit:

- PostgreSQL databases or dumps;
- Odoo filestore or attachments;
- `.env` files, passwords, tokens, private keys, or certificates;
- live `odoo.conf` files containing credentials;
- runtime volumes, sessions, logs, or backups;
- edits made inside a running Odoo container.

## Server connection

Follow [`docs/SERVER-CONNECTION.md`](docs/SERVER-CONNECTION.md) to inventory the Docker deployment, import only custom addons, create a read-only deploy key, mount the repository checkout, and deploy exact reviewed commit SHAs.

The production server must consume this repository through a read-only deploy credential and deploy an exact reviewed commit SHA. Git rollback alone is not sufficient after a database-changing module upgrade; restore the matching database and filestore recovery point when rollback requires data reversal.
