# Odoo repository review — 2026-08-31

> Historical review snapshot. Every figure below was measured against commit
> `7969a09` (`origin/main`) on 2026-08-31. The recommendations remain useful,
> but counts must be re-measured before using them as current release evidence.

Commands are included so each finding can be reproduced against a chosen commit.

## Summary

At the reviewed commit, `main` was healthy: its repository gate passed, every
manifest conformed to policy, and the security model was coherent. The main
risks were unmerged branch debt and thinner coverage in several newer surfaces.

| Check | Result at reviewed commit |
| --- | --- |
| `scripts/run_ci.sh` on `main` | PASS, exit 0 |
| Custom modules | 72 |
| Manifest version policy (`19.0.x.y.z`) | 72/72 conform |
| Modules without tests | **10** |
| `sudo()` calls outside tests | **182** |
| `auth="none"` HTTP routes | **48** |
| Unmerged branches | **83**, of which **61 conflicted** with `main` |

## 1. Branch debt was the largest single problem

```bash
git branch -r | grep -v HEAD | sed 's| *origin/||' | grep -v '^main$'
git merge-tree --write-tree --name-only origin/main origin/<branch>
```

At the reviewed commit, 83 branches were unmerged and 61 of them (73%) no
longer merged into `main` without conflict. Earlier in the same review window
the figures were 72 and 58, indicating rapidly growing stale-branch debt.

Two patterns accounted for much of it:

- A stacked series from `feature/cc-00-mission-foundation` through
  `cc-08-ai-agent-assistant`, plus `test/cc-09`, `release/cc-10`, and
  `fix/cc-11`. Conflict counts rose with position in the stack, from 9 to 112.
- Five duplicated pairs with identical ahead and conflict counts:
  `cc-bu-calderon`/`calderon-farm` (114), `cc-bu-ftp`/`for-the-people` (108),
  `cc-bu-moneybee`/`moneybee-loans` (102), `cc-bu-rlp`/`rlp-real-estate` (105),
  and `cc-bu-scp`/`senior-products` (99).

**Recommendation.** Re-measure each branch against current `main`. Close or
delete a conflicting branch only after confirming that its unique value is
already integrated or deliberately superseded. Triage clean branches first.

## 2. Ten modules shipped with no tests

```bash
for m in custom-addons/*/; do [ -d "$m/tests" ] || basename "$m"; done
```

At the reviewed commit, the untested modules were:

```text
codestra
codestra_ai_review
codestra_ai_call_audit
codestra_analytics_reporting
codestra_ai_core
codestra_daily_reporting
codestra_ai_qualification
codestra_ivr_control
codestra_ai_realtime_assistant
codestra_transcription
```

Six of the ten were AI modules; the remainder covered reporting, IVR, and
transcription. An untested module can break the full runtime installation suite
without a focused unit or smoke test first identifying the defect.

**Recommendation.** Require at least one install-and-smoke test per module, with
the AI modules first because they formed the largest untested block.

## 3. There were 182 `sudo()` calls outside tests

```bash
grep -rn "\.sudo()" --include=*.py custom-addons | grep -v /tests/ | wc -l
```

The calls were concentrated:

| Module | Calls at reviewed commit |
| --- | ---: |
| `codestra_campaign_crm_os` | 35 |
| `call_center_campaign` | 32 |
| `codestra_vicidial_crm` | 19 |
| `codestra_vicidial_recording` | 14 |
| `codestra_klyrow_smtp` | 14 |
| `codestra_lead_ingestion` | 13 |

Each `sudo()` bypasses ACLs and record rules. Many may be legitimate—for
example configuration access or reviewed cross-company reads—but the intent
was not consistently documented.

**Recommendation.** Do not mass-refactor blindly. Require a one-line security
justification beside each `sudo()` in the heaviest modules, then add a validator
that rejects new unjustified calls.

## 4. There were 48 `auth="none"` routes

These were generally signed-HMAC integration endpoints. The prevailing design
was sound: `codestra_middleware_bridge` authenticated a canonical request with
security headers and resolved a per-tenant service identity before ORM access.

The risk was inventory and reviewability. Every `auth="none"` route is an
unauthenticated entry point until its own verification code succeeds.

**Recommendation.** Generate a CI inventory containing route path, module, and
authentication mechanism. Fail on any `auth="none"` route absent from a reviewed
allowlist. This should extend the existing canonical API inventory rather than
create a parallel authority.

## 5. One constraint-style outlier

`codestra_marketing_crm` used the pre-Odoo-19 `_sql_constraints` list form,
while the other reviewed modules declaring SQL constraints used
`models.Constraint`.

**Recommendation.** Convert the outlier and make `review_modules.py` reject new
legacy constraint declarations.

## What the review did not cover

- Runtime behavior. The 463-test runtime add-ons job required Docker and
  PostgreSQL and was not run during that static review.
- PR #5’s runtime add-ons failure. Static analysis had eliminated obvious
  causes, but the install/test-time failure required its exact CI log.
- Whether every then-clean branch contained unique value.

## Recommended order

1. Re-measure and consolidate conflicting or duplicate branches.
2. Add tests for untested modules, AI modules first.
3. Annotate and validate privileged `sudo()` use.
4. Add the reviewed `auth="none"` route inventory gate.
5. Convert the legacy `_sql_constraints` declaration.

This historical document is advisory evidence only. It does not authorize a
production deployment, Odoo database migration, live write, or runtime
activation.