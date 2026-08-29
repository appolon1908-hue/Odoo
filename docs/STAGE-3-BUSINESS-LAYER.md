# Stage 3 — Odoo business layer

## Decision

Stage 3 is one atomic Odoo integration branch, not one branch per existing
business module. The 67-module canonical baseline already separates business
capabilities by add-on. The Stage 3 change crosses the CRM bridge, its security
contract, and the shared recovery harness, so splitting those changes would
create uncertifiable intermediate states.

Branch: `feature/stage-3-business-layer-v1`

Production activation remains disabled. Only a reviewed protected merge may be
promoted to staging.

## Required business capability map

| Required capability | Canonical Odoo owners | Stage 3 disposition |
| --- | --- | --- |
| Contacts, leads, and opportunities | `crm`, `call_center_core`, `codestra_cc_crm`, `codestra_middleware_bridge` | Existing real CRM models retained; signed canonical lead upsert added and tested. |
| Call history and follow-up | `codestra_cc_calls`, `codestra_vicidial_crm`, `codestra_interaction_workflow` | Existing models and activity command retained. |
| Callback and appointment records | `codestra_appointments`, `codestra_cc_calls` | Existing callback/appointment models and pop-outs retained. |
| Consent and preferences | `call_center_compliance`, `codestra_cc_compliance` | Bridge now writes the canonical immutable consent ledger and contact eligibility state. |
| Communication history | `codestra_cc_mail`, `codestra_mail_inbox`, `codestra_cc_omnichannel`, `codestra_middleware_bridge` | Existing history/delivery models retained. |
| Provisioning link | `codestra_identity_provisioning`, `codestra_cc_identity` | Existing approval, read-back, and reconciliation models retained. |

## Middleware write boundary

The resource-specific endpoint is:

```text
POST /codestra/middleware/v1/commands/crm.lead.upsert
```

It accepts the canonical Middleware `crm.lead.upsert` v1 command and rejects
arbitrary model names, methods, domains, SQL, unknown fields, unsupported
versions, mismatched signed headers, unsafe review state, unknown Odoo mappings,
and service identities that span more than one company or business unit.

The endpoint creates or updates a real `crm.lead` through the Odoo ORM. It also
records the stable external mapping, immutable command/idempotency evidence,
correlation metadata, immutable channel consent evidence, and hashed suppression
state in the same request transaction. Explicit denial creates suppression;
unknown review-pending consent blocks contact but does not falsely label the
person as DNC.

No external PostgreSQL credential or direct database write path is introduced.

## Paired recovery authority

`scripts/run_odoo_module_tests.sh` creates a synthetic attachment in the Odoo
filestore after install and upgrade, then captures a custom-format PostgreSQL
dump and matching filestore archive while no Odoo process is writing. It restores
both under an isolated database name and verifies:

- Odoo registry, administrator, schema, and all custom module states;
- exactly one restored sentinel attachment;
- the restored attachment resolves to a physical filestore object;
- the bytes read through Odoo match the expected SHA-256 digest.

The rehearsal is disposable CI evidence. Production backup identifiers and
archives remain outside Git and must still be captured and rehearsed before a
production module upgrade.

## Exit-gate evidence

| Gate | Required evidence | Current state |
| --- | --- | --- |
| Odoo source/security | 67 manifests, strict boundary and mission validators | PASS locally |
| Odoo intake runtime | Authenticated command creates one real lead with correct consent/suppression and replay safety | PENDING CI |
| Paired recovery | Database plus filestore restore and attachment checksum | PENDING CI |
| Middleware-to-Odoo end-to-end | Stage 2 adapter sends the canonical command to this endpoint and reconciles read-back | BLOCKED — Middleware repository still marks the Odoo adapter source as missing |
| Staging certification | Exact merged SHA deployed to staging with external capabilities closed | PENDING protected merge |

Stage 3 is not complete until every row is PASS. Source implementation alone is
not production certification.
