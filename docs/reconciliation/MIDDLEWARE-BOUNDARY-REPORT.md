# Middleware boundary report

Candidate: `feat/cc-compliance-audit` / `4681d755039ee7f4fec21228bac234a668541de8`

Odoo may own transactional outbox/inbox and resource-specific service operations. Cross-system connector execution remains in Codestra Middleware.

## Automated scan

No competing Middleware platform, external PostgreSQL connection, direct VICIdial database write, or named provider HTTP write was detected.

- `EMBEDDED_MIDDLEWARE_PLATFORMS=0`
- `DIRECT_EXTERNAL_POSTGRESQL_CONNECTIONS=0`
- `DIRECT_VICIDIAL_DATABASE_WRITES=0`
- `DIRECT_NAMED_PROVIDER_HTTP_WRITES=0`

This inventory is a deterministic source scan. Certification additionally requires the strict integration-boundary and mission-security CI gates.
