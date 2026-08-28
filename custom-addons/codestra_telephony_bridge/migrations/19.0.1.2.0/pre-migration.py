def migrate(cr, version):
    cr.execute(
        """
        SELECT count(*)
          FROM codestra_integration_result_inbox
         WHERE result_domain = 'TELEPHONY'
        """
    )
    telephony_results = cr.fetchone()[0]
    cr.execute(
        "SELECT %s::integer AS legacy_telephony_result_count",
        [telephony_results],
    )
