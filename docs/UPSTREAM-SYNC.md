# Codestra Odoo upstream synchronization

## Decision

`appolon1908-hue/Odoo` is the destination repository that will be reviewed,
protected, released, and used. `Codestra-SRL/codestra-odoo-addons` is a private
upstream source repository whose complete contents are imported through a pull
request.

The sync does not make the organization repository a deployment authority. It
makes the personal Odoo repository contain the upstream source, preserves exact
upstream provenance, and promotes every discovered addon into the destination's
canonical `custom-addons` runtime path.

## Confidentiality gate

The complete upstream source must not be imported while
`appolon1908-hue/Odoo` is public. Before the first plan or import run, change the
destination repository visibility to **private** and verify that only approved
collaborators and GitHub Apps retain access.

The workflow queries GitHub immediately after checkout and fails unless the
destination reports:

```text
visibility=private
```

It then scans the full upstream Git history with the same pinned Gitleaks
version used by the destination security workflow. No source file is copied and
no import branch is pushed unless that scan passes. This gate protects both
organization intellectual property and credentials that may exist in historical
commits.

Changing visibility is an owner-controlled GitHub setting and is not performed
by the sync workflow.

## Why the import is controlled

Blindly replacing the destination Git tree would erase newer protected work,
repository security controls, CI, CODEOWNERS, review evidence, and target-only
modules. The controlled sync therefore does all of the following:

1. verifies the destination repository is private;
2. checks out an exact upstream branch, tag, or commit;
3. scans the complete upstream Git history for secrets before copying source;
4. records the exact source commit and tree SHA;
5. stores the complete source tree at `upstream/codestra-odoo-addons`;
6. overlays every non-governance source file at the destination root;
7. copies every directory containing `__manifest__.py` or `__openerp__.py` to
   `custom-addons/<module_name>`;
8. lets upstream source win when the same non-governance path exists in both
   repositories;
9. preserves destination `.github`, CODEOWNERS, workflows, README, secret
   scanning configuration, and sync-controller files;
10. removes only paths recorded as managed by an earlier successful sync;
11. retains target-only addons until a separate disposition is reviewed;
12. opens a normal pull request and never writes directly to protected `main`.

The upstream `.github` directory is preserved inside the complete snapshot but
is not activated as destination workflow authority.

## Private-source credential

The GitHub Actions repository secret below must exist in the private
`appolon1908-hue/Odoo` repository:

```text
CODESTRA_ODOO_UPSTREAM_READ_TOKEN
```

Use a fine-grained personal access token or GitHub App installation token with:

```text
resource owner: Codestra-SRL
repository access: Codestra-SRL/codestra-odoo-addons only
repository permission: Contents — Read-only
expiration: short and reviewed
organization SSO: authorized when the organization requires it
```

Do not grant Administration, Actions write, pull-request write, secrets, or
access to unrelated repositories. Never paste the token into a workflow input,
issue, pull request, commit, documentation, chat, or log.

Installing the GitHub integration on the `Codestra-SRL` organization is also
recommended for direct read/review access, but the import workflow still uses
the explicitly scoped repository secret.

## First synchronization

After the sync-controller PR is merged:

1. Change `appolon1908-hue/Odoo` visibility to **private**.
2. Re-audit collaborators, deploy keys, Actions, GitHub Apps, and branch rules.
3. Add `CODESTRA_ODOO_UPSTREAM_READ_TOKEN` under **Settings → Secrets and
   variables → Actions**.
4. Open **Actions → Sync Codestra Odoo addons upstream**.
5. Run with:

   ```text
   upstream_ref=main
   operation=plan
   ```

6. Verify the workflow records `DESTINATION_VISIBILITY=private` and
   `UPSTREAM_FULL_HISTORY_SECRET_SCAN=PASS`.
7. Inspect the exact source SHA, source tree, module count, managed-file count,
   target-only modules, and diff.
8. Run again with:

   ```text
   upstream_ref=<the reviewed exact SHA or main>
   operation=pull-request
   ```

9. Review the generated `sync/codestra-odoo-*` pull request.
10. Merge only after exact-head, merge-result, Odoo module, source-security, and
    review-thread gates pass.

The first import intentionally does not delete destination-only source. A later
cleanup requires a branch/module disposition manifest.

## Runtime use

The sync promotes all discovered upstream modules into:

```text
custom-addons/<module_name>
```

The reviewed runtime should include this repository path in Odoo's addons path,
for example:

```text
addons_path = /usr/lib/python3/dist-packages/odoo/addons,/srv/codestra-odoo/custom-addons
```

The path shown above is an example. The real staging and production path must be
verified from the deployment repository and server evidence rather than copied
blindly.

Importing source is not module installation. After the generated PR merges, use
an isolated staging restore to:

- record the exact destination commit;
- reconcile installed module versions;
- upgrade only reviewed modules;
- validate migrations and record counts;
- run duplicate, altered-replay, tenant-isolation, and timeout-after-commit
  reconciliation tests;
- verify paired PostgreSQL and filestore backup/restore;
- rehearse rollback.

## Deterministic state and deletion rules

The workflow writes:

```text
config/upstream-sync-state.json
upstream/codestra-odoo-addons/.source.json
```

The state records the exact source SHA/tree, every managed overlay file, every
promoted module and its content digest, and target-only modules.

On later runs:

- a source path that changed is updated;
- a source path that disappeared is deleted only when the previous state proves
  it was upstream-managed;
- a target-only file or addon is not deleted automatically;
- duplicate upstream module names fail closed;
- broken or repository-escaping symlinks fail closed;
- promoted module content must match its recorded digest.

## Permanent safety state

```text
DESTINATION_VISIBILITY=private
UPSTREAM_FULL_HISTORY_SECRET_SCAN=required
ODOO_WRITE=false
LIVE_WRITE=false
ENABLE_EXTERNAL_DELIVERY=false
LIVE_SMS_DELIVERY=false
LIVE_EMAIL_DELIVERY=false
LIVE_PSTN_DIALING=false
PRODUCTION_DIALING=DISABLED
WORKFLOWS_ACTIVE=NO
DATABASE_MIGRATION=NO
DEPLOYMENT_AUTHORIZED=NO
```

The sync workflow copies source and opens a review PR only. It does not connect
to an Odoo server, install a module, update a database, modify a filestore,
provision a credential, activate n8n, reload Kong/Caddy, or change staging or
production.
