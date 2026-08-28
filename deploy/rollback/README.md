# Rollback procedure

1. Close the affected channel and prevent new outbox dispatch.
2. Preserve logs, database evidence, correlation IDs, failed events, and the deployed release identity.
3. Restore the prior immutable add-on artifact or image digest.
4. Restore data only when the reviewed migration rollback requires it, using the verified backup and restoration procedure.
5. Restart only the required Odoo services and workers.
6. Verify database, queue, authentication, record rules, screen-pop read behavior, and reconciliation.
7. Keep email, SMS, callbacks, n8n, live call control, and PSTN dialing disabled.
8. Create an incident and attach mismatch and recovery evidence.

Rollback rehearsal is `BLOCKED` until performed against isolated staging.
