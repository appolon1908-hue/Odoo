def migrate(cr, version):
    """Quarantine historical result rows whose immutable outbox was deleted.

    No result is deleted and no replacement event is fabricated.  The original
    numeric reference is retained for audit while only the invalid FK candidate
    is cleared before Odoo enforces the relational constraint.
    """
    cr.execute(
        """
        ALTER TABLE codestra_integration_result_inbox
          ADD COLUMN IF NOT EXISTS originating_outbox_legacy_id integer
        """
    )
    cr.execute(
        """
        ALTER TABLE codestra_integration_result_inbox
          ALTER COLUMN originating_outbox_id DROP NOT NULL
        """
    )
    cr.execute(
        """
        UPDATE codestra_integration_result_inbox AS result
           SET originating_outbox_legacy_id = result.originating_outbox_id,
               originating_outbox_id = NULL,
               reconciliation_status = 'REVIEW_REQUIRED',
               error_class = COALESCE(result.error_class, 'LEGACY_OUTBOX_MISSING'),
               error_summary = COALESCE(
                   result.error_summary,
                   'Historical originating outbox record is unavailable; numeric reference preserved.'
               )
         WHERE result.originating_outbox_id IS NOT NULL
           AND NOT EXISTS (
               SELECT 1
                 FROM codestra_integration_outbox AS outbox
                WHERE outbox.id = result.originating_outbox_id
           )
        """
    )
