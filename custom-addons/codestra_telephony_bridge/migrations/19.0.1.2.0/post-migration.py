def migrate(cr, version):
    cr.execute(
        """
        UPDATE codestra_integration_result_inbox
           SET command_public_id = operation_public_id
         WHERE result_domain = 'TELEPHONY'
           AND command_public_id IS NULL
           AND operation_public_id IS NOT NULL
        """
    )
    backfilled_rows = cr.rowcount
    cr.execute(
        """
        SELECT count(*)
          FROM codestra_integration_result_inbox
         WHERE result_domain = 'TELEPHONY'
           AND operation_public_id IS NOT NULL
           AND command_public_id IS NULL
        """
    )
    incompatible_rows = cr.fetchone()[0]
    if incompatible_rows:
        raise RuntimeError(
            "Telephony API migration found results without operation identity: "
            f"{incompatible_rows}"
        )
    cr.execute(
        "SELECT %s::integer AS backfilled_command_binding_count",
        [backfilled_rows],
    )
