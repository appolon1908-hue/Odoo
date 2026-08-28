# `feat/cc-scripts-dispositions` close-out

Status: `PARTIAL` / `STAGING-ONLY` / `PRODUCTION_BLOCKED`

Base: `feat/cc-vicidial-mapping` at
`12775a51209a2eb1c5be7d2a50c1ad635f804398`

## Implemented

- Converted `codestra_cc_disposition` from an empty dependency facade into the
  canonical scripts/dispositions governance layer.
- Added `cc.script`, delegated `cc.script.version`, and append-only
  `cc.script.acknowledgement` models.
- Added separate submission/approval, immutable approved content, one approved
  version per script, SHA-256 content binding, server-derived rendering, and
  internal-field redaction.
- Added `cc.disposition.set` and delegated `cc.disposition` schemas with
  campaign/channel matching, one approved set per campaign, six-character native
  status validation, source hashes, workflow/event metadata, and immutable rows.
- Added global campaign record rules, operational approved-state filters,
  restricted sensitive fields, blocked bulk export, configuration views, ACLs,
  rollback guidance, and synthetic runtime tests.
- Generated 93-row script and 93-row disposition reconciliation matrices from
  the controlled identifier report.

## Validation

- `C:\Program Files\Git\bin\bash.exe scripts/run_ci.sh`: PASS.
- 63 manifests reviewed; 0 strict review errors/warnings.
- Mission security: no unrestricted `sudo()`, raw SQL, direct network writer, or
  public controller in the module.
- Odoo 19/PostgreSQL exact-head runtime: pending draft-PR execution.

## Unresolved gates

- The original `odoo_campaign_disposition_catalog.csv` is still missing. The
  authority says it contains exactly 2,677 controlled rows; prose examples are
  not an authorized substitute.
- Consequently, every disposition set starts blocked, review/approval cannot
  pass, zero catalog rows are imported, and external publication/read-back is
  `NOT_TESTED`.
- The authority attachment remains incomplete at its ending, and no reviewed
  isolated staging endpoint was supplied.

## Rollback

Return the stack to `feat/cc-vicidial-mapping` or restore the disposable
pre-upgrade database. Do not delete adopted legacy records. No live external or
production state was changed.
