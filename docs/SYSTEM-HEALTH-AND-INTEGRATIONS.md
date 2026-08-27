# Odoo system health and integration review

Reviewed: 2026-08-27

## Verified health

- 32 custom addons have unique technical names under `custom-addons/`.
- Every manifest parses and every declared local data file exists.
- All Python files compile and all XML files parse.
- All 32 addons install together on Odoo 19 with PostgreSQL 16.
- `codestra_vicidial_crm` installs from a clean database and its focused
  click-to-call tests pass.
- The call action blocks missing/unready agents, DNC records, invalid numbers,
  missing business units, unauthorized campaigns, and missing compliance
  configuration before any network request.
- Policy-denied calls are reported as blocked and are never shown as placed.

## Runtime configuration required for click-to-call

Store these as protected Odoo system parameters; do not commit their values:

- `codestra.middleware.telephony_originate_url`
- `codestra.middleware.api_key`
- `codestra.telephony.destination_class`
- `codestra.telephony.destination_country`

The destination class and country are explicit because guessing them from a
phone prefix is unsafe for shared numbering plans such as `+1`.

## API and service integrations

| Integration | Odoo implementation | Boundary |
|---|---|---|
| Codestra Middleware | `codestra_middleware_bridge`, `codestra_integration_hub`, `codestra_telephony_bridge` | Approved cross-system API writer and event transport |
| VICIdial | `codestra_vicidial_connector`, `codestra_vicidial_crm`, `codestra_vicidial_recording` | Odoo requests actions through Middleware; inbound events use authenticated contracts |
| Keycloak / identity provisioning | `codestra_identity_provisioning` | Private provisioning-service contract; no passwords or tokens stored in business records |
| n8n | integration contracts and outbox/result models | Orchestration only; no direct Odoo database or unrestricted model access |
| MoneyBee | CRM identity mapping contract | Middleware-mediated contact/account projection |
| SMS, email, crawler and AI services | integration hub, lead automation, mail inbox, AI addons | External effects default disabled and require platform capability gates |

## Remaining non-blocking findings

- Several imported manifests omit the optional `author` field.
- Some internal/service-only models intentionally have no normal-user ACL; the
  warning should be reviewed whenever a UI is added for those models.
- Two CRM fields use the same display label, `External Source`; their technical
  names differ, but the UI wording should be clarified.
- A few model docstrings produce reStructuredText formatting warnings.
- Full production calling is not proven by repository tests because it requires
  protected Middleware configuration, an authorized campaign, a ready agent,
  and an explicitly enabled dialing policy. Repository tests deliberately mock
  the Middleware response and never place a PSTN call.
