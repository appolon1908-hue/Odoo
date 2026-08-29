# Odoo contact-center production gate

Assessment date: 2026-08-28

Recommendation: `STAGING-ONLY`

Gate: `PRODUCTION_BLOCKED`

This authority branch does not claim an implemented or production-ready contact
center. The complete membership security boundary, controlled disposition input,
identifier migration, isolated mail/CRM/Helpdesk surfaces, staging integration
read-back, synthetic tests, migration/rollback evidence, and all required reports
are outstanding.

All live and delivery feature flags must remain false. A future `GO` decision
requires separate human production approval after every gate in section 32 of the
authority is evidenced; this specification authorizes only staging work.
