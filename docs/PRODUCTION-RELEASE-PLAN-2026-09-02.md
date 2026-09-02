# Codestra Odoo production release plan — 2026-09-02

## Repository and release links

- Repository: https://github.com/appolon1908-hue/Odoo
- Current protected-main intake merge: https://github.com/appolon1908-hue/Odoo/commit/2015c682c0b6e37b306d8a2b75ee025578637b2e
- Merged intake/CRM PR: https://github.com/appolon1908-hue/Odoo/pull/57
- Operational endpoints PR: https://github.com/appolon1908-hue/Odoo/pull/58
- Canonical Middleware/Odoo command-contract PR: https://github.com/appolon1908-hue/Odoo/pull/53
- Upstream source-authority importer PR: https://github.com/appolon1908-hue/Odoo/pull/55
- Automated-governance documentation PR: https://github.com/appolon1908-hue/Odoo/pull/59

## Current decision

`main` is a tested source baseline and the intake/CRM layer is merged. It is not yet a production-certified runtime.

The production release chain is:

```text
PR #58 operational endpoints
  -> signed OCI production-candidate controls
  -> PR #53 canonical cross-repository command contract
  -> exact-main candidate build and attestations
  -> production source-authority reconciliation
  -> current paired backup
  -> isolated-staging upgrade and restart
  -> Caddy -> Kong -> Middleware -> Odoo certification
  -> representative paired restore
  -> rollback rehearsal
  -> production read-only canary
  -> bounded soak and reconciliation
  -> explicit production activation
```

## Gate matrix

| Gate | Repository state | Completion rule |
|---|---|---|
| Intake/CRM PR #57 | PASS / merged | Exact main CI and security remain green |
| Middleware-only write boundary | Implemented | PR #53 must freeze the byte-exact command/signature contract across Odoo, Middleware, and n8n |
| Operational endpoints | PR #58 exact-head green | Independent approval and protected merge are still required |
| Immutable production artifact | Implemented by this release-control branch | Run the manual workflow from signed `main`; retain the OCI digest |
| Complete container SBOM | Implemented by this release-control branch | Retain Trivy SPDX JSON and signed SBOM attestation |
| Provenance and signature | Implemented by this release-control branch | Retain GitHub OIDC/Sigstore provenance and SBOM attestation URLs/bundles |
| Production deployment evidence | BLOCKED | Exact image digest must be observed on the target runtime |
| Staging-to-production promotion | BLOCKED | Isolated staging must pass the evidence contract before any production apply |
| Backup and restore | BLOCKED | Create a fresh paired database-plus-filestore backup, verify checksums and off-host copy, and restore both |
| Rollback rehearsal | BLOCKED | Restore prior source, database, and filestore and pass post-rollback smoke tests |
| Canary and soak | BLOCKED | Read-only canary first; then bounded soak with zero unexpected writes and controlled reconciliation backlog |
| Full contact-center completion | PARTIAL | Reconcile open draft/stacked feature branches separately; do not bundle incomplete features into this release |
| Repository governance | PARTIAL | Required checks, conversation resolution, force-push/deletion protection, and release permissions must be verified in GitHub settings |

## Immutable candidate contract

The production image is:

```text
ghcr.io/appolon1908-hue/odoo@sha256:<digest>
```

The informational tag is:

```text
ghcr.io/appolon1908-hue/odoo:sha-<40-character-main-sha>
```

The workflow refuses to overwrite an existing SHA tag. Runtime manifests must consume the digest reference, never `latest` and never the tag alone.

The image is built without package-manager or network mutation from:

```text
docker.io/library/odoo@sha256:f54272f31d5f77e4146b887efb3761c98480317daf687e4b4b5e76ed8bcc08c5
```

Only reviewed `custom-addons/` are added. The container defaults to the non-root `odoo` identity.

## Repository-side certification

Before candidate publication:

- selected ref must be `main`;
- expected SHA must equal the workflow SHA and checked-out SHA;
- GitHub commit verification must report a valid signature;
- `scripts/run_ci.sh` must pass;
- the production container must build;
- the image must contain no symbolic links under `/mnt/extra-addons`;
- no embedded-secret finding is permitted;
- fixed critical vulnerabilities block publication;
- complete high/critical findings are retained as evidence;
- all actions are pinned to immutable commit SHAs;
- the registry tag must not already exist.

After publication:

- resolve the immutable registry digest;
- create signed SLSA provenance;
- create a signed SBOM attestation;
- generate the production-candidate manifest;
- regenerate SHA-256 checksums for the complete evidence bundle.

## Runtime evidence contract

Copy `release/production-evidence-template.json` into a release-specific sanitized evidence file. Validate it with:

```bash
python3 scripts/validate_production_evidence.py \
  --file release/evidence/<release-id>.json
```

The validator fails closed unless the selected verdict has all required evidence. A `BLOCKED` template is accepted only for repository CI with `--allow-blocked-template`.

### Staging certification

Use the exact candidate digest against an isolated staging database and filestore. Keep all live effects false:

```text
LIVE_ODOO_WRITE=false
ENABLE_EXTERNAL_DELIVERY=false
EMAIL_DELIVERY=false
SMS_DELIVERY=false
CALLBACK_DISPATCH=false
PSTN_DIALING=false
N8N_ACTIVATION=false
VICIDIAL_LIVE_CONTROL=false
```

Required staging evidence:

- source SHA and image digest read-back;
- fresh paired backup;
- affected-module upgrade;
- interrupted-upgrade restart;
- schema, administrator, and module audits;
- negative authorization and tenant isolation;
- Caddy, Kong, Middleware, and Odoo route/contract checks;
- idempotent duplicate and altered-payload conflict behavior;
- zero unexpected external effects;
- representative database-plus-filestore restore.

### Production read-only canary

The canary must use the exact staging-certified digest. `LIVE_ODOO_WRITE` and every external-effect flag remain false. Observe health, readiness, version, capabilities, logs, error rate, database connections, cron behavior, reconciliation queues, and proxy behavior. Any source/image mismatch, unexpected write, authentication drift, migration discrepancy, or rising error rate stops the release.

### Production activation

Production activation is a separate operation. It requires:

- successful read-only canary;
- rehearsed rollback;
- current backup/restore evidence;
- bounded soak limits;
- explicit list of approved live capabilities;
- exact capability read-back after activation;
- no unrelated channel activation.

A source merge or signed image does not authorize live writes, email, SMS, callbacks, PSTN, n8n activation, or VICIdial control.

## Known external blockers

The last sanitized server inventory reported a mutable host checkout that did not match GitHub, version/content drift, an old paired backup, and no representative production-data restore. Those facts must be re-audited; the old report cannot certify the current release.

The repository is public. Do not add secrets, customer data, database dumps, filestore content, private addresses, or live configuration. The separate upstream-sync path requires a private destination and a protected read-only source credential before it can be executed.

## Final certification semantics

Use only these release outcomes:

- `BLOCKED`
- `STAGING_CERTIFIED`
- `PRODUCTION_READ_ONLY_CANARY_CERTIFIED`
- `PRODUCTION_CERTIFIED`

`PRODUCTION_CERTIFIED` is valid only when the exact source SHA and image digest are deployed and every required runtime field passes the machine-readable evidence validator.
