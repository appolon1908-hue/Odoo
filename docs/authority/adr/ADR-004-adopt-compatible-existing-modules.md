# ADR-004: Adopt compatible modules before adding new domain modules

- Status: Accepted for staging implementation
- Date: 2026-08-28

## Decision

The target 38-module architecture is implemented as bounded domain modules, but
compatible existing records and workflows are adopted rather than duplicated.
Existing `codestra_cc_*` dependency facades may become stable composition modules.
Concrete legacy models receive explicit compatibility links or migrations to the
new `cc.*` foundation. There is one authoritative record for each business unit,
campaign, membership, mapping, script version, disposition outcome, callback,
recording, and policy.

Before a new model is introduced, its legacy owner, keys, record volume, security,
and migration path are documented in the model matrix. Compatibility fields are
temporary, read-only for agents, and removed only after upgrade and rollback tests.

## Consequences

Module-name presence alone does not count as implementation: six target-named
modules currently exist only as dependency facades. The branch stack begins with
the core domain and security boundary, then composes CRM, mail, telephony, and
business-unit overlays in dependency order.
