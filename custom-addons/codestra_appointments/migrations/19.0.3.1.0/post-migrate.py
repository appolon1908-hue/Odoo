def migrate(cr, version):
    """Restartably reconcile legacy and governed callback columns."""
    cr.execute(
        "ALTER TABLE IF EXISTS codestra_callback "
        "DROP CONSTRAINT IF EXISTS codestra_callback_owner_required"
    )
    cr.execute(
        "ALTER TABLE IF EXISTS codestra_callback ALTER COLUMN lead_id DROP NOT NULL"
    )
    cr.execute(
        "ALTER TABLE IF EXISTS codestra_callback ALTER COLUMN owner_id DROP NOT NULL"
    )
    cr.execute(
        "ALTER TABLE IF EXISTS codestra_callback ALTER COLUMN call_id DROP NOT NULL"
    )
    cr.execute(
        """
        UPDATE codestra_callback AS callback
           SET assigned_agent_id = COALESCE(callback.assigned_agent_id, callback.owner_id),
               owner_id = COALESCE(callback.owner_id, callback.assigned_agent_id),
               phone_number = COALESCE(callback.phone_number, callback.phone),
               normalized_phone = COALESCE(callback.normalized_phone, callback.phone_number, callback.phone),
               phone = COALESCE(callback.phone, callback.phone_number),
               customer_timezone = COALESCE(callback.customer_timezone, callback.timezone, 'UTC'),
               timezone = COALESCE(callback.timezone, callback.customer_timezone, 'UTC'),
               name = COALESCE(callback.name, callback.reason, 'Callback ' || callback.id::text),
               correlation_id = COALESCE(callback.correlation_id, 'legacy-callback-' || callback.id::text),
               idempotency_key = COALESCE(callback.idempotency_key, 'legacy-callback-' || callback.id::text),
               state = COALESCE(
                   callback.state,
                   CASE callback.status
                       WHEN 'completed' THEN 'completed'
                       WHEN 'cancelled' THEN 'cancelled'
                       ELSE 'scheduled'
                   END
               ),
               status = COALESCE(
                   callback.status,
                   CASE callback.state
                       WHEN 'completed' THEN 'completed'
                       WHEN 'cancelled' THEN 'cancelled'
                       WHEN 'scheduled' THEN 'scheduled'
                       ELSE NULL
                   END
               ),
               business_unit_id = COALESCE(callback.business_unit_id, unit.id)
          FROM call_center_business_unit AS unit
         WHERE callback.business_unit_id IS NULL
           AND upper(unit.code) = upper(callback.tenant_id)
        """
    )

    cr.execute(
        """
        UPDATE codestra_callback AS callback
           SET assigned_agent_id = COALESCE(callback.assigned_agent_id, callback.owner_id),
               owner_id = COALESCE(callback.owner_id, callback.assigned_agent_id),
               phone_number = COALESCE(callback.phone_number, callback.phone),
               normalized_phone = COALESCE(callback.normalized_phone, callback.phone_number, callback.phone),
               phone = COALESCE(callback.phone, callback.phone_number),
               customer_timezone = COALESCE(callback.customer_timezone, callback.timezone, 'UTC'),
               timezone = COALESCE(callback.timezone, callback.customer_timezone, 'UTC'),
               name = COALESCE(callback.name, callback.reason, 'Callback ' || callback.id::text),
               correlation_id = COALESCE(callback.correlation_id, 'legacy-callback-' || callback.id::text),
               idempotency_key = COALESCE(callback.idempotency_key, 'legacy-callback-' || callback.id::text),
               state = COALESCE(callback.state, 'scheduled')
         WHERE callback.business_unit_id IS NOT NULL
        """
    )
