# Codestra Scrapper Projection

This Odoo 19 addon is the business-system-of-record boundary for normalized business
records produced by the Codestra Scrapper pipeline.

Only the tenant-bound Middleware service identity may call
`codestra.scrapper.business.apply_middleware_projection`. The method accepts a
bounded, versioned business payload; it never accepts raw crawler pages, provider
credentials, arbitrary model names, SQL, or executable templates.

## Safety properties

- exact service-user and tenant binding through Odoo configuration parameters;
- durable event receipts with content-bound idempotency;
- monotonic business versions with same-version conflict rejection;
- PostgreSQL uniqueness plus transactional savepoints for concurrent first-writer
  races, without opening an external database connection;
- audit-retained projections and immutable receipts;
- no outbound network call, crawler execution, email, SMS, dialing, or provider
  activation;
- no secret committed to this repository.

## Required non-secret configuration

```text
codestra.scrapper.tenant_ids=<comma-separated canonical tenant UUIDs>
codestra.middleware.tenant.<tenant-uuid>.codestra.scrapper.service_user_id=<Odoo user id>
```

The configured user must belong to **Codestra Scrapper Projection Service**.
Auditors receive read-only access. Direct create, update, or deletion remains
blocked even for those groups; changes flow only through the governed service
method.
