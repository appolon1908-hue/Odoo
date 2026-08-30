# Odoo 19 integration boundary

**Status:** Accepted and binding for Codestra Odoo customizations.

## Canonical authority decision

Codestra Middleware adopts the governed `/v2/automation/*` control plane used by
n8n. Odoo remains the business system of record and accepts external business
mutations only from Codestra Middleware through the reviewed
`codestra_middleware_bridge` module.

The canonical CRM flow is:

```text
n8n-crm-automation
  -> Kong
  -> POST /v2/automation/commands
  -> Middleware durable command and Temporal execution
  -> POST /codestra/middleware/v1/commands/crm.lead.upsert
  -> Odoo transaction and immutable command evidence
  -> GET /codestra/middleware/v1/commands/{command_id}/status
  -> Middleware reconciliation
  -> GET /v2/automation/commands/{command_id}
  -> n8n
```

The historical n8n `/v1/integrations/n8n/*` routes and Odoo direct CRM CRUD
routes are compatibility aliases only. They are not competing canonical
interfaces and must not be used for new workflow development.

## System-of-record responsibility

Odoo 19 is the business system of record for:

- customers and contacts;
- leads and opportunities;
- activities and campaigns;
- call history;
- post-call forms and notes;
- callbacks and appointments;
- consent and communication preferences;
- SMS and email history;
- delivery results;
- agent and supervisor business views;
- business reporting.

This repository contains the reviewed custom modules, tests, migrations, and
deployment controls that implement those business capabilities. It does not
contain the PostgreSQL database, filestore, credentials, certificates, runtime
sessions, logs, backups, or edits copied from a running container.

## Authorized cross-system writer

Codestra Middleware is the only authorized cross-system writer.

External portals, n8n, telephony systems, SMS/email systems, social systems,
crawlers, provider services, and reporting tools must not connect directly to
Odoo PostgreSQL or receive Odoo database write credentials.

Middleware may write through only one of these approved interfaces:

1. a narrow Odoo service API implemented by a reviewed custom module; or
2. a reviewed ORM bridge that executes resource-specific commands inside Odoo.

Both interfaces are Odoo application interfaces. Neither is a generic database proxy or unrestricted RPC-to-model adapter.

## Canonical bridge contract

The reviewed bridge module is `codestra_middleware_bridge`.

```text
COMMAND_TYPE=crm.lead.upsert
COMMAND_VERSION=1.0
TARGET=odoo-19
CAPABILITY=ODOO_WRITE
POST /codestra/middleware/v1/commands/crm.lead.upsert
GET  /codestra/middleware/v1/commands/{command_id}/status
```

The command body, signed headers, and durable Middleware identity must agree on:

- command ID / `X-Codestra-Event-ID`;
- tenant ID / `X-Tenant-ID`;
- correlation ID / `X-Correlation-ID`;
- idempotency key / `Idempotency-Key`.

The canonical HMAC-SHA256 input joins the following byte sequences with one
newline, in this exact order:

```text
X-Codestra-Timestamp
X-Codestra-Event-ID
HTTP method in uppercase
request path
X-Tenant-ID
X-Correlation-ID
Idempotency-Key
raw request body
```

The tenant is authorized from the verified Middleware principal and configured
Odoo tenant/service mapping. A header alone never grants tenant authority. The
bridge first resolves a tenant-specific signing secret and service identity.
For backward compatibility, current source falls back to global values for an
allowlisted tenant when tenant-specific values are absent. That fallback is not
tenant-isolated and must not be used in multi-tenant production. Multi-tenant
promotion requires tenant-specific secret and service-identity bindings for
every allowed tenant and removal of the global fallback values.

## Unknown-outcome rule

A write response timeout is an unknown outcome, not proof that Odoo rejected
the command. Middleware must query the command-status route before any retry.

```text
blind command resubmission after unknown outcome = prohibited
command-status reconciliation before retry = required
```

If the command was recorded, Middleware returns the recorded result to its
caller. If it was not recorded, the command remains unresolved until the
reviewed retry policy authorizes a retry using the same semantic identity.
Operators must never repair this state by editing Odoo tables.

## Compatibility routes

The following routes remain temporarily available for reviewed legacy callers:

- `POST /codestra/middleware/v1/crm/leads`;
- `GET|PATCH /codestra/middleware/v1/crm/leads/{external_id}`;
- `POST /codestra/middleware/v1/crm/activities`.

They are deprecated compatibility surfaces. New CRM ingestion must use the
canonical command route. Removing an alias requires a separately reviewed
consumer inventory and sunset change.

## Bridge requirements

Before activation the bridge must:

- authenticate a dedicated Middleware service identity;
- enforce least-privilege access controls and record rules;
- resolve the authoritative tenant, company, and business scope;
- accept versioned resource-specific commands;
- reject caller-selected arbitrary model names, method names, domains, SQL, or field sets;
- validate required business fields and state transitions;
- use the Odoo ORM for business writes;
- use raw SQL only in reviewed migration code when the ORM cannot perform the migration safely;
- store the Middleware command ID and idempotency key in the same transaction as the business change;
- preserve stable mappings between Middleware identifiers and Odoo records;
- use optimistic concurrency or an explicit expected version where overwrite risk exists;
- return the original result for an already-applied command;
- preserve correlation IDs and a safe audit trail;
- provide reconciliation queries that do not expose unrestricted ORM access.

## Database rule

No external service may write directly to Odoo PostgreSQL.

The Odoo application role remains the business-write database identity. Backup
tooling, monitoring, migrations, and approved maintenance use separate
least-privilege identities and procedures. A read-only reporting role does not
become a write path.

The custom-addons repository must not introduce separate PostgreSQL client
connections, embedded database passwords, `DATABASE_URL` values, or shell calls
to `psql` as an integration mechanism. Reviewed Odoo migration scripts may use
the Odoo-managed cursor inside the controlled module-upgrade transaction.

## Idempotency and reconciliation

Every Middleware-originated mutation must carry:

- a stable Middleware command ID;
- a stable idempotency key;
- tenant and company context;
- correlation and causation identifiers;
- the command schema version;
- a stable external source-record identity;
- the expected resource version when applicable.

The Odoo bridge stores the applied command identity atomically with the business
change. Concurrent duplicates must result in one applied mutation. A retry
returns the existing result rather than creating another lead, activity,
appointment, call record, message-history entry, or delivery result.

## Testing gates

A module that implements or changes the integration boundary must prove:

1. unauthenticated and unauthorized service identities fail;
2. cross-company and cross-tenant access fails;
3. record rules and access-control lists are effective;
4. malformed and unsupported command versions fail;
5. duplicate and concurrent commands apply once;
6. the command ledger and business change commit or roll back together;
7. state-transition and optimistic-concurrency conflicts are deterministic;
8. audit and correlation data is preserved;
9. no generic model-write endpoint exists;
10. no external Odoo PostgreSQL write credential is required;
11. the exact HMAC golden vector matches the Middleware implementation;
12. timeout-after-commit is reconciled through command status with zero blind resubmissions;
13. clean install, upgrade, migration rollback, and paired database/filestore recovery are tested;
14. staging starts with external delivery and live integration writes disabled.

## Deployment boundary

Only a reviewed protected merged SHA is deployed. The affected modules are
upgraded in staging first. Production uses the identical accepted artifact
after a matching PostgreSQL and filestore recovery point, explicit approval,
smoke testing, and a rehearsed rollback procedure.

Git rollback by itself is not a safe rollback after a data-changing Odoo module
upgrade. Database and filestore recovery must match the module revision when
data reversal is required.

This source contract does not enable `ODOO_WRITE`, external delivery, live
workflow execution, deployment, or production mutation.
