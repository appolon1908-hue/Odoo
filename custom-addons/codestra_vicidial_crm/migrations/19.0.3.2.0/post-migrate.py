def migrate(cr, version):
    """Recover VICIdial campaign links from the immutable source-call link."""
    cr.execute(
        """
        UPDATE codestra_callback AS callback
           SET vicidial_campaign_id = source_call.campaign_id
          FROM codestra_vicidial_call AS source_call
         WHERE callback.call_id = source_call.id
           AND callback.vicidial_campaign_id IS NULL
           AND source_call.campaign_id IS NOT NULL
        """
    )
