def migrate(cr, version):
    """Backfill safe defaults without inventing external observations."""
    cr.execute(
        """
        UPDATE codestra_telephony_desired_state
           SET observed_state_version = COALESCE(
                   observed_state_version, actual_state_version, 0
               ),
               observed_asterisk_contact_count = COALESCE(
                   observed_asterisk_contact_count, 0
               ),
               desired_state_updated_at = COALESCE(
                   desired_state_updated_at, write_date, create_date
               )
         WHERE observed_state_version IS NULL
            OR observed_asterisk_contact_count IS NULL
            OR desired_state_updated_at IS NULL
        """
    )
    backfilled_row_count = cr.rowcount
    cr.execute(
        """
        SELECT count(*)
          FROM codestra_telephony_desired_state
         WHERE observed_state_version IS NULL
            OR observed_asterisk_contact_count IS NULL
            OR desired_state_updated_at IS NULL
        """
    )
    incompatible_row_count = cr.fetchone()[0]
    if incompatible_row_count:
        raise RuntimeError(
            "Telephony projection migration left incompatible rows: "
            f"{incompatible_row_count}"
        )
    cr.execute(
        "SELECT %s::integer AS backfilled_row_count",
        [backfilled_row_count],
    )
