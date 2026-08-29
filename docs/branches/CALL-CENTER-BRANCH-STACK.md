# Corporate Call Center Branch Stack

## Baseline

The stack begins from `feature/codestra-login-admin-readiness` at its current reviewed source head. That branch already contains the Middleware-only write boundary, the Odoo 19 login module, static module review and isolated runtime CI.

The call-center branches are deliberately source-only. They do not install modules, migrate a live database, activate n8n, deliver email or SMS, place calls, or deploy to staging or production.

## Merge and implementation order

| Order | Branch | Scope | Required base |
|---:|---|---|---|
| 00 | `feature/cc-00-mission-foundation` | Sanitized mission, branch registry, OpenAPI skeleton and policy validation | `feature/codestra-login-admin-readiness` |
| 01 | `feature/cc-01-core-reliability` | Core interaction schema, inbox/outbox, audit and migrations | 00 |
| 02 | `feature/cc-02-vicidial-api` | VICIdial events, call reconciliation, screen-pop and API controllers | 01 |
| 03 | `feature/cc-03-agent-campaign-experience` | Agent desktop, campaigns, dispositions, customer 360 and publishing | 01, 02 |
| 04 | `feature/cc-04-supervisor-quality-compliance` | Supervisor controls, QA, compliance and case management | 03 |
| 05 | `feature/cc-05-workforce-identity-onboarding` | Workforce, identity provisioning, onboarding and training | 01, 04 |
| 06 | `feature/cc-06-omnichannel-client-operations` | Omnichannel, mailboxes, allowlisted automation and client operations | 03, 05 |
| 07 | `feature/cc-07-revenue-analytics-portal` | Revenue, analytics, data quality and client portal | 03, 04, 06 |
| 08 | `feature/cc-08-ai-agent-assistant` | Human-reviewed summaries, suggestions and draft responses | 03, 04, 06 |
| 09 | `test/cc-09-security-load-migrations` | Cross-cutting security, browser, migration, load and recovery evidence | 01–08 |
| 10 | `release/cc-10-staging-certification` | Immutable artifact and isolated staging certification | 09 |

All implementation branches are created from the mission-foundation commit so they are available immediately. When code begins, each pull request must be based or rebased onto the exact dependency head shown above. No branch may claim dependency evidence merely because the branch name exists.

## Module ownership

### Branch 01

- `codestra_cc_core`
- `codestra_cc_reliability`
- `codestra_cc_audit`

### Branch 02

- `codestra_cc_vicidial`

### Branch 03

- `codestra_cc_agent_desktop`
- `codestra_cc_campaign`
- `codestra_cc_disposition`
- `codestra_cc_customer_360`
- `codestra_campaign_publishing`

### Branch 04

- `codestra_cc_supervisor`
- `codestra_cc_quality`
- `codestra_cc_compliance`
- `codestra_case_management`

### Branch 05

- `codestra_cc_workforce`
- `codestra_cc_identity`
- `codestra_agent_onboarding`
- `codestra_training_academy`

### Branch 06

- `codestra_cc_omnichannel`
- `codestra_cc_mailbox`
- `codestra_cc_automation`
- `codestra_client_operations`

### Branch 07

- `codestra_revenue_assurance`
- `codestra_cc_analytics`
- `codestra_data_quality`
- `codestra_client_portal`

### Branch 08

- `codestra_ai_agent_assistant`

A module moves between branches only through a reviewed update to the machine-readable workstream registry.

## Pull request rules

Every implementation PR must state:

1. exact base and head SHA;
2. modules and data models changed;
3. migration, upgrade and rollback impact;
4. ACL, record-rule and negative authorization evidence;
5. API and event schema impact;
6. idempotency, retry and reconciliation behavior;
7. test results and known gaps;
8. capability flags that remain false;
9. staging and production status;
10. next safe action.

PRs remain draft while schema, security, migration or contract work is incomplete. Independent review must target the final unchanged head. Normal protected merging is required; administrator bypass is prohibited.

## Database discipline

Schema changes are introduced only through Odoo module upgrades and reviewed, restartable migration hooks. Historical external IDs, interaction links, consent evidence and audit records are preserved. No record may be deleted merely to make a migration pass.

Before a unique constraint is enabled, the implementation must detect existing duplicates and create a manager review path for ambiguous records. Before production promotion, backup and isolated restore evidence must cover both database and filestore consistency.

## Runtime discipline

The release branch is not a deployment workflow. It holds release and staging evidence only. Live activation remains outside these feature branches and requires:

- exact merged source identity;
- immutable image digest;
- SBOM and provenance;
- staging certification;
- rollback rehearsal;
- independent approval;
- private runtime preflight;
- channel-specific provider and compliance authorization.

Email, SMS, callbacks, n8n delivery and PSTN dialing are enabled independently. A failed channel gate closes that channel without enabling another one as a workaround.
