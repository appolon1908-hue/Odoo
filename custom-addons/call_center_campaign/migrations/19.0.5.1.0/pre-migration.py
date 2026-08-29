def migrate(cr, version):
    """Refuse an unsafe result uniqueness upgrade.

    Existing delivery bindings are immutable evidence. Ambiguous duplicate
    deliveries must be investigated and reconciled instead of being deleted or
    silently rewritten by a migration.
    """
    cr.execute("SELECT to_regclass('codestra_runtime_integration_outbox')")
    outbox_exists = cr.fetchone()[0] is not None
    cr.execute("SELECT to_regclass('codestra_integration_result_inbox')")
    result_inbox_exists = cr.fetchone()[0] is not None

    if outbox_exists:
        cr.execute(
            """
            ALTER TABLE codestra_runtime_integration_outbox
            ADD COLUMN IF NOT EXISTS idempotency_key varchar
            """
        )
        cr.execute(
            """
            UPDATE codestra_runtime_integration_outbox
               SET idempotency_key = deterministic_event_key
             WHERE idempotency_key IS NULL
            """
        )
        cr.execute(
            """
            ALTER TABLE codestra_runtime_integration_outbox
            ALTER COLUMN idempotency_key SET NOT NULL
            """
        )

    if not result_inbox_exists:
        return

    # Preserve legacy evidence whose original outbox table/row is absent, but
    # quarantine the stale integer before Odoo adds the new foreign key.
    cr.execute(
        """
        ALTER TABLE codestra_integration_result_inbox
        ADD COLUMN IF NOT EXISTS originating_outbox_legacy_id integer
        """
    )
    if outbox_exists:
        cr.execute(
            """
            UPDATE codestra_integration_result_inbox AS result
               SET originating_outbox_legacy_id = result.originating_outbox_id,
                   originating_outbox_id = NULL
             WHERE result.originating_outbox_id IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1
                     FROM codestra_runtime_integration_outbox AS outbox
                    WHERE outbox.id = result.originating_outbox_id
               )
            """
        )
    else:
        cr.execute(
            """
            UPDATE codestra_integration_result_inbox
               SET originating_outbox_legacy_id = originating_outbox_id,
                   originating_outbox_id = NULL
             WHERE originating_outbox_id IS NOT NULL
            """
        )
    cr.execute(
        """
        SELECT delivery_id, count(*)
          FROM codestra_integration_result_inbox
         GROUP BY delivery_id
        HAVING count(*) > 1
         LIMIT 1
        """
    )
    duplicate = cr.fetchone()
    if duplicate:
        raise RuntimeError(
            "Cannot enforce unique result delivery binding: "
            f"delivery {duplicate[0]} has {duplicate[1]} result records"
        )
