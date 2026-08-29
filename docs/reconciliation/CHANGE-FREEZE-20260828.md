# Odoo canonicalization change freeze — 2026-08-28

## Status

The Odoo source repository is under a canonicalization freeze effective 2026-08-28. The freeze remains active until one protected `main`, one approved custom-addon inventory, one read-only production baseline, one server-to-GitHub reconciliation ledger, and one staging-certified release candidate exist.

## Allowed work

- source, branch, pull-request, module, API, and runtime reconciliation;
- security and access-control corrections;
- CI correctness and supply-chain security;
- migration correctness and restartability;
- immutable deployment and recovery tooling;
- read-only runtime capture;
- staging and production-readiness evidence.

## Frozen work

No new campaign, business-unit, AI, email, SMS, VICIdial, CRM, reporting, WFM, compliance, frontend-widget, or provider-integration feature may enter the canonicalization branch.

## Safety boundary

Discovery and reconciliation must not install, upgrade, uninstall, or change a live Odoo module; alter the production database or filestore; restart production merely to collect evidence; activate n8n; change Kong, Keycloak, Middleware, or VICIdial; send email or SMS; place PSTN calls; or deploy production.

The Codestra Middleware remains the authority for cross-system authorization, durable commands and events, retries, replay, connector execution, cross-system idempotency, and reconciliation. Odoo owns business state and resource-specific ORM operations. This repository must not contain another generic middleware or provider-connector platform.

## Exit gate

The freeze may be lifted only after the reconciliation pull request has passed required review and CI, live drift has no unknown classification, isolated install/upgrade/recovery/access-control tests pass, and staging certification identifies an exact source SHA and immutable runtime evidence. Production deployment remains a separate approval.
