# Codestra Odoo 19 Production Readiness Plan

**Repository:** `appolon1908-hue/Odoo`  
**Production verdict at plan creation:** `NO_GO`  
**Safe current use:** exact-SHA release candidate and isolated staging only

## Objective

Promote one protected `main` SHA into one immutable Odoo 19 runtime artifact, prove that artifact in isolated staging, prove backup and rollback, then use a bounded production canary. A source merge is never treated as deployment evidence.

## Current established baseline

- PR #57, the unified intake CRM upsert, is merged to `main`.
- Current-main Odoo Addons CI and Security gates have produced successful runs.
- Middleware is the only approved cross-system write boundary.
- Live Odoo writes, external delivery, n8n activation and PSTN dialing remain disabled by default.

This is enough to begin a release candidate. It is not enough to issue `PRODUCTION_CERTIFIED=YES`.

## Production-critical repository order

### 1. Operational contract

Review and promote PR #58 only after its exact head passes all required checks. It supplies canonical `/health`, `/ready`, `/version`, and `/capabilities` aliases. Readiness must fail closed when dependencies or safety configuration are not ready; capabilities must report effective runtime gates rather than desired configuration.

### 2. Integration contract

Review PR #53 together with its named Middleware and n8n counterparts. Promote it only when the HMAC vector, command route, tenant/correlation/idempotency ordering, unknown-outcome reconciliation and compatibility aliases are byte-compatible across repositories.

### 3. Governance

Do not weaken `main` while repository rules are absent or unverified. Before production promotion, enforce:

- required exact-head Odoo Addons CI and Security checks;
- no force push and no branch deletion;
- no administrator bypass;
- review-thread resolution;
- a protected `odoo-production-certification` environment;
- immutable evidence retention;
- either independent approval or a formally reviewed automated-equivalent policy with separation of duties.

PR #59 must not be used to remove safeguards before those controls exist and are evidenced.

### 4. Immutable release candidate

Build the complete runtime from one protected `main` SHA. Record:

- source SHA;
- image digest, never a mutable tag alone;
- Odoo and PostgreSQL image digests;
- installed addon inventory and exact tree hashes;
- release manifest and checksums;
- runtime-image SBOM;
- vulnerability report;
- build provenance;
- signature and verification output.

The source repository can validate the evidence bundle but must not fabricate runtime evidence that belongs to the build/deployment authority.

### 5. Isolated staging certification

Deploy the immutable digest to an isolated staging database and filestore. Prove:

- fresh installation and upgrade from the currently deployed schema;
- module inventory and database schema readback;
- `/health`, `/ready`, `/version`, and `/capabilities` through Caddy and Kong;
- Caddy → Kong → Middleware → Odoo signed command flow;
- idempotency replay, altered-body conflict and unknown-outcome reconciliation;
- tenant/company/campaign isolation and negative authorization;
- live delivery, Odoo writes, n8n delivery, email, SMS and PSTN remain disabled during the no-effect phase;
- logs, metrics, alerts and correlation IDs are visible.

Odoo-write certification is a separate isolated phase after the no-effect ingress phase passes.

### 6. Backup and restore

For the same source SHA and image digest:

- create PostgreSQL and filestore backups;
- store encrypted off-host copies;
- restore into a clean isolated target;
- validate database/filestore pairing, attachments and module state;
- record RPO and RTO;
- run post-restore health, readiness and reconciliation checks.

### 7. Rollback rehearsal

Prove application rollback to the prior digest. Classify database compatibility as reversible, forward-compatible or restore-required. Run post-rollback health, readiness, smoke and reconciliation checks. A rollback plan that has not been executed is not evidence.

### 8. Canary and soak

Use a bounded canary with explicit tenant/campaign scope, error budget, latency thresholds, queue limits, database saturation limits, reconciliation checks and automatic stop conditions. Expand only after the soak exit criteria pass.

### 9. Production activation

Require a change record binding:

- source SHA and artifact digest;
- staging, backup/restore, rollback and canary evidence hashes;
- operator and rollback owner;
- activation window;
- capability changes;
- post-deploy smoke and reconciliation results.

Only then may the evidence bundle set every gate to `PASS`, `production_certified=true`, and `verdict=GO`.

## Machine gate

Policy: `config/production-certification.v1.json`  
Validator: `scripts/validate_production_certification.py`  
Evidence template: `evidence/production/production-evidence.template.json`

Policy validation:

```bash
python3 scripts/validate_production_certification.py
```

Final evidence validation for an exact protected-main SHA:

```bash
python3 scripts/validate_production_certification.py \
  --evidence evidence/production/production-evidence.json \
  --expected-source-sha "$SOURCE_SHA" \
  --assert-certified
```

Until that command passes against authentic retained evidence, the only valid result is:

```text
PRODUCTION_CERTIFIED=NO
PRODUCTION_VERDICT=NO_GO
```

## Explicit non-actions in this repository change

- no server access;
- no Odoo module installation or upgrade;
- no database or filestore mutation;
- no Caddy or Kong runtime apply;
- no secret binding;
- no provider activation;
- no email, SMS or call;
- no production deployment.
