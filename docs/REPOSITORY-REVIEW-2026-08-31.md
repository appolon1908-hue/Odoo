# Odoo repository review — 2026-08-31

Reviewed commit: `7969a09` (`origin/main`).

Every figure below was measured against that commit, not estimated. Commands are
given so each one can be re-derived.

## Summary

`main` is healthy. Its own gate passes clean, every manifest conforms to policy,
and the security model is coherent. The problems are not in the code that has
landed — they are in the code that has not, and in three areas where coverage is
thinner than the surrounding rigour would suggest.

| Check | Result |
| --- | --- |
| `scripts/run_ci.sh` on `main` | PASS, exit 0 |
| Custom modules | 72 |
| Manifest version policy (`19.0.x.y.z`) | 72/72 conform |
| Modules without tests | **10** |
| `sudo()` calls outside tests | **182** |
| `auth="none"` HTTP routes | **48** |
| Unmerged branches | **83**, of which **61 conflict** with `main` |

## 1. Branch debt is the largest single problem, and it is growing

```bash
git branch -r | grep -v HEAD | sed 's| *origin/||' | grep -v '^main$'
git merge-tree --write-tree --name-only origin/main origin/<branch>
```

83 branches are unmerged. 61 of them (73%) no longer merge into `main` without
conflict. Earlier in the same review window the figures were 72 and 58, so the
set is growing by roughly one rotted branch per day.

Two patterns account for most of it:

* **A stacked series that has rotted.** `feature/cc-00-mission-foundation`
  through `cc-08-ai-agent-assistant`, plus `test/cc-09`, `release/cc-10` and
  `fix/cc-11`. Conflict counts rise monotonically with position in the stack,
  from 9 to 112. Rebasing the tail is not economic.
* **Five duplicated pairs**, each pair with identical ahead-counts and identical
  conflict counts: `cc-bu-calderon`/`calderon-farm` (114), `cc-bu-ftp`/
  `for-the-people` (108), `cc-bu-moneybee`/`moneybee-loans` (102), `cc-bu-rlp`/
  `rlp-real-estate` (105), `cc-bu-scp`/`senior-products` (99). The same work was
  committed twice under two names.

**Recommendation.** Treat the 61 conflicting branches as closed unless someone
can name what each contains that is not already on `main`. Delete rather than
rebase. The 22 that still merge cleanly are the only ones worth triage.

## 2. Ten modules ship with no tests

```bash
for m in custom-addons/*/; do [ -d "$m/tests" ] || basename "$m"; done
```

```
codestra                      codestra_ai_review
codestra_ai_call_audit        codestra_analytics_reporting
codestra_ai_core              codestra_daily_reporting
codestra_ai_qualification     codestra_ivr_control
codestra_ai_realtime_assistant  codestra_transcription
```

They are not randomly distributed: **six of the ten are the AI modules**, and the
remainder are reporting, IVR and transcription. Every module that touches
consent, campaign scope, telephony dispatch or the Middleware boundary has
tests. The untested set is precisely the newer, less-governed surface.

This matters because the runtime addons job installs every module. An untested
module can break the whole suite for reasons no unit test would have caught
first, which makes failures more expensive to diagnose than they need to be.

**Recommendation.** Require at least an install-and-smoke test per module. The
AI modules should be first, because they are the largest untested block.

## 3. 182 `sudo()` calls outside tests

```bash
grep -rn "\.sudo()" --include=*.py custom-addons | grep -v /tests/ | wc -l
```

Concentrated rather than spread:

| Module | Calls |
| --- | --- |
| `codestra_campaign_crm_os` | 35 |
| `call_center_campaign` | 32 |
| `codestra_vicidial_crm` | 19 |
| `codestra_vicidial_recording` | 14 |
| `codestra_klyrow_smtp` | 14 |
| `codestra_lead_ingestion` | 13 |

Each `sudo()` bypasses both ACLs and record rules. This repository invests
heavily in record-rule design — the global `crm.lead` rules alone encode admin,
manager, integration-service, supervisor and agent branches — and every
`sudo()` is a point where that design does not apply.

Most are likely legitimate (config parameters, cross-company reads). The risk is
that there is no way to tell which, because they are not annotated.

**Recommendation.** Not a mass refactor. Require a one-line justification comment
on each `sudo()` in the two heaviest modules, then add a validator asserting the
comment exists. That converts an unreviewable 182 into a reviewable list, and
makes new unjustified ones fail CI.

## 4. Forty-eight `auth="none"` routes

These are the signed-HMAC integration endpoints, and the pattern is sound —
`codestra_middleware_bridge` authenticates by HMAC over a canonical string that
includes the security headers, then resolves a per-tenant service identity
before touching the ORM.

The concern is inventory rather than design: 48 is enough that no reviewer holds
them all in mind, and each is an unauthenticated entry point until its own code
says otherwise.

**Recommendation.** Generate the route inventory in CI — path, module,
authentication mechanism — and fail on any `auth="none"` route that does not
appear in a reviewed allowlist. The repository already validates a canonical API
inventory; this is an extension of that mechanism, not a new one.

## 5. One constraint-style outlier

`codestra_marketing_crm` uses the pre-19 `_sql_constraints` list form. The other
45 modules that declare SQL constraints use Odoo 19's `models.Constraint`.

It works today, so this is drift rather than a defect — but it is the kind of
drift that gets copied into the next module by whoever reads that one first.

**Recommendation.** Convert it, and add the check to `review_modules.py`.

## What this review did not cover

* Runtime behaviour. Every figure here is static. The 463-test runtime addons
  job requires Docker and PostgreSQL and was not run.
* PR #5, whose runtime addons CI is failing. Static analysis eliminated the
  obvious causes — it is up to date with `main`, passes `run_ci.sh`, its model
  `_name` matches its ACL and `ir.rule` references, and it does not carry the
  two Odoo 19 defects corrected in #22 — but the failure is at install or test
  time and needs the CI log.
* Whether the 22 cleanly-merging branches contain anything of value.

## Priority

1. Close or delete the 61 conflicting branches. Largest effort saved per hour.
2. Tests for the ten untested modules, AI modules first.
3. Annotate `sudo()` in `codestra_campaign_crm_os` and `call_center_campaign`.
4. Route inventory gate for `auth="none"`.
5. Convert the `_sql_constraints` outlier.
