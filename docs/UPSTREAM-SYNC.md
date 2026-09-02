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

It then scans the full upstream Git history using the destination-preserved
`.gitleaks.toml`. An upstream branch cannot weaken this scan with its own broad
allowlist. No source file is copied and no import branch is pushed unless the
scan passes.

Changing visibility is an owner-controlled GitHub setting and is not performed
by the sync workflow.

## Protected credential environment

Create a GitHub environment named exactly:

```text
odoo-upstream-source-sync
```

Configure it before storing the source credential:

- deployment branches/tags: **selected branch `main` only**;
- required reviewers: at least one trusted reviewer who can inspect the exact
  requested upstream ref and workflow run;
- prevent self-review where a second trusted reviewer is available;
- no environment URL and no deployment action;
- environment secrets:

  ```text
  CODESTRA_ODOO_UPSTREAM_READ_TOKEN
  ODOO_SYNC_PR_TOKEN
  ```

Do **not** store either token as an ordinary repository secret. A manual workflow
can be selected from another branch, so a repository secret could be exposed to
an unreviewed workflow definition. The job itself also requires
`github.ref == refs/heads/main`, but the environment branch restriction is the
credential boundary.

Use a short-lived fine-grained token or GitHub App installation token with:

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

`ODOO_SYNC_PR_TOKEN` is a separate fine-grained credential limited to
`appolon1908-hue/Odoo`, with Contents and Pull requests write permissions only.
The `publish` job is bound to the same main-restricted protected environment,
so an unreviewed workflow ref cannot obtain this destination write credential.

Installing the GitHub integration on the `Codestra-SRL` organization is also
recommended for direct read/review access, but the import workflow still uses
the explicitly scoped protected-environment secret.

## Why the import is controlled

Blindly replacing the destination Git tree would erase newer protected work,
repository security controls, CI, CODEOWNERS, review evidence, and target-only
modules. The controlled sync therefore:

1. runs only from the trusted destination `main` workflow;
2. obtains the source token only through the protected environment;
3. verifies the destination repository is private;
4. checks out an exact upstream branch, tag, or commit;
5. scans the complete upstream history with the destination Gitleaks policy;
6. records the exact source commit and tree SHA;
7. stores the complete source tree at `upstream/codestra-odoo-addons`;
8. overlays every non-governance source file at the destination root;
9. promotes each module containing `__manifest__.py` or `__openerp__.py` to
   `custom-addons/<module_name>`;
10. lets upstream source win on non-governance collisions;
11. preserves destination `.github`, `config`, `scripts`, `tests/security`,
    README, secret-scanning policy, and sync-controller files;
12. verifies the preserved validation-file hashes before running CI;
13. removes only paths recorded as managed by an earlier successful sync;
14. retains target-only addons until a separate disposition is reviewed;
15. rejects duplicate addon names and addon symlinks that would change meaning
    after relocation;
16. reuses an existing immutable sync branch only when its Git tree exactly
    matches the new candidate;
17. opens a normal pull request and never writes directly to protected `main`.

The upstream `.github`, configuration, scripts, and tests remain available in
the complete provenance snapshot, but they do not replace destination
governance authority.

## First synchronization

After the sync-controller PR is merged:

1. Change `appolon1908-hue/Odoo` visibility to **private**.
2. Re-audit collaborators, deploy keys, Actions, GitHub Apps, and branch rules.
3. Create and protect environment `odoo-upstream-source-sync` as described
   above.
4. Add `CODESTRA_ODOO_UPSTREAM_READ_TOKEN` and `ODOO_SYNC_PR_TOKEN` to that
   environment only.
5. Open **Actions → Sync Codestra Odoo addons upstream** on branch `main`.
6. Run:

   ```text
   upstream_ref=main
   operation=plan
   ```

7. Verify the run records:

   ```text
   SYNC_WORKFLOW_CONTEXT=TRUSTED_MAIN
   DESTINATION_VISIBILITY=private
   UPSTREAM_FULL_HISTORY_SECRET_SCAN=PASS
   DESTINATION_VALIDATION_AUTHORITY_UNCHANGED=YES
   ```

8. Inspect the exact source SHA/tree, module count, managed-file count,
   target-only modules, and diff.
9. Run again with:

   ```text
   upstream_ref=<reviewed exact SHA or main>
   operation=pull-request
   ```

10. Review the generated `sync/codestra-odoo-*` pull request.
11. Merge only after exact-head, merge-result, Odoo module, source-security, and
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

That path is an example. The real staging and production path must be verified
from the deployment repository and server evidence.

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

- changed source paths are updated;
- disappeared source paths are deleted only when previous state proves they
  were upstream-managed;
- file-to-directory and directory-to-file transitions are handled before copy;
- target-only files and addons are not deleted automatically;
- duplicate module names fail closed;
- broken, escaping, or excluded-target symlinks fail closed;
- addon symlinks require explicit disposition before promotion;
- promoted module content must match its recorded digest;
- an existing sync branch is reused only when its tree is identical;
- a different tree for the same source/base identity fails as nondeterministic
  instead of being force-pushed.

## Permanent safety state

```text
DESTINATION_VISIBILITY=private
PROTECTED_ENVIRONMENT=odoo-upstream-source-sync
UPSTREAM_FULL_HISTORY_SECRET_SCAN=required
DESTINATION_VALIDATION_AUTHORITY_UNCHANGED=required
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
provision a runtime credential, activate n8n, reload Kong/Caddy, or change
staging or production.
