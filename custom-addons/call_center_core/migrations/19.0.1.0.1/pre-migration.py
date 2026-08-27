def migrate(cr, version):
    """Classify unscoped legacy leads without weakening the required field."""
    cr.execute(
        """
        SELECT res_id
          FROM ir_model_data
         WHERE module = 'call_center_core'
           AND name = 'business_unit_shared'
           AND model = 'call.center.business.unit'
        """
    )
    row = cr.fetchone()
    if not row:
        raise RuntimeError(
            "Cannot backfill legacy leads: Shared Services business unit is missing"
        )

    cr.execute(
        """
        UPDATE crm_lead
           SET business_unit_id = %s
         WHERE business_unit_id IS NULL
        """,
        [row[0]],
    )
