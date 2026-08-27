def migrate(cr, version):
    """Inventory existing projections and reject ambiguous identities."""
    cr.execute("SELECT count(*) FROM codestra_telephony_desired_state")
    pre_migration_row_count = cr.fetchone()[0]
    cr.execute(
        """
        SELECT record_environment, employee_id, campaign_id, count(*)
          FROM codestra_telephony_desired_state
         GROUP BY record_environment, employee_id, campaign_id
        HAVING count(*) > 1
        """
    )
    conflicts = cr.fetchall()
    if conflicts:
        raise RuntimeError(
            "Telephony projection migration requires manual conflict review: "
            f"{len(conflicts)} incompatible identities"
        )
    cr.execute(
        "SELECT %s::integer AS pre_migration_row_count",
        [pre_migration_row_count],
    )
