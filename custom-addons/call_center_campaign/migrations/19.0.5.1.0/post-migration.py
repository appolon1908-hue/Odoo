def migrate(cr, version):
    """Backfill newly introduced compatibility bindings conservatively."""
    cr.execute("SELECT to_regclass('codestra_runtime_integration_outbox')")
    if cr.fetchone()[0] is not None:
        cr.execute(
            """
            UPDATE codestra_runtime_integration_outbox
               SET aggregate_record_id = campaign_id
             WHERE aggregate_record_id IS NULL
            """
        )
    cr.execute("SELECT to_regclass('codestra_integration_result_inbox')")
    if cr.fetchone()[0] is not None:
        cr.execute(
            """
            UPDATE codestra_integration_result_inbox
               SET completed_at = COALESCE(processed_at, received_at)
             WHERE processing_status = 'PROCESSED'
               AND completed_at IS NULL
            """
        )
