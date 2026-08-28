def migrate(cr, version):
    """Preserve the legacy VICIdial campaign FK under an unambiguous name."""
    # A legacy combined installation let `codestra_appointments` replace this
    # model in place. Remove those richer physical requirements before the base
    # callback owner is upgraded; its dependent module backfills them later.
    cr.execute(
        "ALTER TABLE IF EXISTS codestra_callback "
        "DROP CONSTRAINT IF EXISTS codestra_callback_owner_required"
    )
    optional_columns = (
        ("lead_id", "ALTER COLUMN lead_id DROP NOT NULL"),
        ("owner_id", "ALTER COLUMN owner_id DROP NOT NULL"),
        ("call_id", "ALTER COLUMN call_id DROP NOT NULL"),
        ("business_unit_id", "ALTER COLUMN business_unit_id DROP NOT NULL"),
        ("callback_uuid", "ALTER COLUMN callback_uuid DROP NOT NULL"),
        ("normalized_phone", "ALTER COLUMN normalized_phone DROP NOT NULL"),
        ("phone_number", "ALTER COLUMN phone_number DROP NOT NULL"),
        ("customer_timezone", "ALTER COLUMN customer_timezone DROP NOT NULL"),
        ("correlation_id", "ALTER COLUMN correlation_id DROP NOT NULL"),
        ("idempotency_key", "ALTER COLUMN idempotency_key DROP NOT NULL"),
        ("state", "ALTER COLUMN state DROP NOT NULL"),
        ("middleware_sync_state", "ALTER COLUMN middleware_sync_state DROP NOT NULL"),
        ("version", "ALTER COLUMN version DROP NOT NULL"),
    )
    for column_name, alter_clause in optional_columns:
        cr.execute(
            """
            SELECT 1
              FROM information_schema.columns
             WHERE table_name = 'codestra_callback'
               AND column_name = %s
            """,
            (column_name,),
        )
        if cr.fetchone():
            # `alter_clause` comes only from the fixed allowlist above.
            cr.execute("ALTER TABLE codestra_callback " + alter_clause)

    cr.execute(
        """
        SELECT target.relname
          FROM pg_constraint constraint_row
          JOIN pg_class target ON target.oid = constraint_row.confrelid
          JOIN unnest(constraint_row.conkey) AS key(attnum) ON TRUE
          JOIN pg_attribute attribute
            ON attribute.attrelid = constraint_row.conrelid
           AND attribute.attnum = key.attnum
         WHERE constraint_row.conrelid = to_regclass('codestra_callback')
           AND constraint_row.contype = 'f'
           AND attribute.attname = 'campaign_id'
         LIMIT 1
        """
    )
    target = cr.fetchone()
    if not target or target[0] != "codestra_vicidial_campaign":
        return
    cr.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = 'codestra_callback'
           AND column_name = 'vicidial_campaign_id'
        """
    )
    if cr.fetchone():
        return
    cr.execute(
        "ALTER TABLE codestra_callback RENAME COLUMN campaign_id TO vicidial_campaign_id"
    )
    cr.execute(
        """
        ALTER TABLE codestra_callback
        RENAME CONSTRAINT codestra_callback_campaign_id_fkey
        TO codestra_callback_vicidial_campaign_id_fkey
        """
    )
