def migrate(cr, version):
    """Refuse an unsafe result uniqueness upgrade.

    Existing delivery bindings are immutable evidence. Ambiguous duplicate
    deliveries must be investigated and reconciled instead of being deleted or
    silently rewritten by a migration.
    """
    cr.execute("SELECT to_regclass('codestra_runtime_integration_outbox')")
    if cr.fetchone()[0] is None:
        # The table is introduced by this module version.  Freshly upgrading
        # older databases must let the ORM create it before any backfill runs.
        return

    cr.execute(
        """
        ALTER TABLE codestra_runtime_integration_outbox
        ADD COLUMN IF NOT EXISTS idempotency_key varchar
        """
    )
    cr.execute("SELECT to_regclass('codestra_integration_result_inbox')")
    if cr.fetchone()[0] is None:
        return

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
