def _columns(cr, table_name):
    cr.execute(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = %s
        """,
        [table_name],
    )
    return {row[0] for row in cr.fetchall()}


def migrate(cr, version):
    table_name = "codestra_data_quality_issue"
    cr.execute("SELECT to_regclass(%s)", ["public.%s" % table_name])
    if not cr.fetchone()[0]:
        return

    columns = _columns(cr, table_name)
    if {"safe_detail", "issue_type", "state"} <= columns:
        cr.execute(
            """
            UPDATE codestra_data_quality_issue
               SET safe_detail = COALESCE(safe_detail, '{}'::jsonb)
                   || jsonb_build_object(
                       'legacy_campaign_crm_os_issue_type', issue_type,
                       'legacy_campaign_crm_os_state', state
                   )
             WHERE issue_type IN (
                       'DUPLICATE', 'INVALID_PHONE', 'INVALID_EMAIL',
                       'MISSING_REQUIRED_DATA', 'STALE_LEAD',
                       'UNWORKED_LEAD', 'ORPHAN_ASSIGNMENT'
                   )
                OR state IN ('OPEN', 'REVIEWED', 'RESOLVED', 'WAIVED')
            """
        )

    if "issue_type" in columns:
        cr.execute(
            """
            UPDATE codestra_data_quality_issue
               SET issue_type = CASE issue_type
                   WHEN 'DUPLICATE' THEN 'duplicate'
                   WHEN 'INVALID_PHONE' THEN 'invalid_phone'
                   WHEN 'INVALID_EMAIL' THEN 'invalid_email'
                   WHEN 'MISSING_REQUIRED_DATA' THEN 'missing_required_data'
                   WHEN 'STALE_LEAD' THEN 'stale_lead'
                   WHEN 'UNWORKED_LEAD' THEN 'unworked_lead'
                   WHEN 'ORPHAN_ASSIGNMENT' THEN 'orphan_assignment'
                   ELSE issue_type
               END
             WHERE issue_type IN (
                       'DUPLICATE', 'INVALID_PHONE', 'INVALID_EMAIL',
                       'MISSING_REQUIRED_DATA', 'STALE_LEAD',
                       'UNWORKED_LEAD', 'ORPHAN_ASSIGNMENT'
                   )
            """
        )
    if "state" in columns:
        cr.execute(
            """
            UPDATE codestra_data_quality_issue
               SET state = CASE state
                   WHEN 'OPEN' THEN 'open'
                   WHEN 'REVIEWED' THEN 'in_review'
                   WHEN 'RESOLVED' THEN 'resolved'
                   WHEN 'WAIVED' THEN 'ignored'
                   ELSE state
               END
             WHERE state IN ('OPEN', 'REVIEWED', 'RESOLVED', 'WAIVED')
            """
        )

    cr.execute(
        """
        SELECT company.id, company.partner_id
          FROM ir_model_data data
          JOIN res_company company ON company.id = data.res_id
         WHERE data.module = 'base'
           AND data.name = 'main_company'
           AND data.model = 'res.company'
         LIMIT 1
        """
    )
    main_company = cr.fetchone()
    if not main_company:
        cr.execute("SELECT id, partner_id FROM res_company ORDER BY id LIMIT 1")
        main_company = cr.fetchone()
    if not main_company:
        return
    main_company_id, main_partner_id = main_company

    if {"company_id", "lead_id"} <= columns:
        cr.execute(
            """
            UPDATE codestra_data_quality_issue issue
               SET company_id = lead.company_id
              FROM crm_lead lead
             WHERE issue.company_id IS NULL
               AND issue.lead_id = lead.id
               AND lead.company_id IS NOT NULL
            """
        )
    if {"company_id", "campaign_id"} <= columns:
        cr.execute(
            """
            UPDATE codestra_data_quality_issue issue
               SET company_id = unit.company_id
              FROM call_center_campaign campaign
              JOIN call_center_business_unit unit
                ON unit.id = campaign.business_unit_id
             WHERE issue.company_id IS NULL
               AND issue.campaign_id = campaign.id
               AND unit.company_id IS NOT NULL
            """
        )
    if "company_id" in columns:
        cr.execute(
            """
            UPDATE codestra_data_quality_issue
               SET company_id = %s
             WHERE company_id IS NULL
            """,
            [main_company_id],
        )

    if {"res_model", "res_id", "lead_id"} <= columns:
        cr.execute(
            """
            UPDATE codestra_data_quality_issue
               SET res_model = 'crm.lead',
                   res_id = lead_id
             WHERE lead_id IS NOT NULL
               AND (res_model IS NULL OR res_id IS NULL OR res_id <= 0)
            """
        )
    if {"res_model", "res_id", "campaign_id"} <= columns:
        cr.execute(
            """
            UPDATE codestra_data_quality_issue issue
               SET res_model = 'res.partner',
                   res_id = company.partner_id
              FROM call_center_campaign campaign
              JOIN call_center_business_unit unit
                ON unit.id = campaign.business_unit_id
              JOIN res_company company
                ON company.id = unit.company_id
             WHERE issue.campaign_id = campaign.id
               AND (issue.res_model IS NULL OR issue.res_id IS NULL OR issue.res_id <= 0)
            """
        )
    if {"res_model", "res_id"} <= columns:
        cr.execute(
            """
            UPDATE codestra_data_quality_issue
               SET res_model = 'res.partner',
                   res_id = %s
             WHERE res_model IS NULL
                OR res_id IS NULL
                OR res_id <= 0
            """,
            [main_partner_id],
        )

    if {"issue_type", "duplicate_res_id", "res_id"} <= columns:
        if "safe_detail" in columns:
            cr.execute(
                """
                UPDATE codestra_data_quality_issue
                   SET safe_detail = COALESCE(safe_detail, '{}'::jsonb)
                       || jsonb_build_object(
                           'legacy_duplicate_without_candidate', true
                       )
                 WHERE issue_type = 'duplicate'
                   AND (
                       duplicate_res_id IS NULL
                       OR duplicate_res_id <= 0
                       OR duplicate_res_id = res_id
                   )
                """
            )
        cr.execute(
            """
            UPDATE codestra_data_quality_issue
               SET issue_type = 'cross_reference'
             WHERE issue_type = 'duplicate'
               AND (
                   duplicate_res_id IS NULL
                   OR duplicate_res_id <= 0
                   OR duplicate_res_id = res_id
               )
            """
        )

    if "severity" in columns:
        cr.execute(
            """
            UPDATE codestra_data_quality_issue
               SET severity = '1'
             WHERE severity IS NULL OR severity = ''
            """
        )
    if "name" in columns:
        cr.execute(
            """
            UPDATE codestra_data_quality_issue
               SET name = 'LEGACY-DQ-' || id::text
             WHERE name IS NULL OR name = '' OR name = 'New'
            """
        )
    if "idempotency_key" in columns:
        cr.execute(
            """
            UPDATE codestra_data_quality_issue
               SET idempotency_key = 'legacy-campaign-crm-os:' || id::text
             WHERE idempotency_key IS NULL OR idempotency_key = ''
            """
        )
    if "issue_uuid" in columns:
        cr.execute(
            """
            UPDATE codestra_data_quality_issue
               SET issue_uuid = 'legacy-campaign-crm-os-' || id::text
             WHERE issue_uuid IS NULL OR issue_uuid = ''
            """
        )
    if "correlation_id" in columns:
        cr.execute(
            """
            UPDATE codestra_data_quality_issue
               SET correlation_id = 'legacy-campaign-crm-os-' || id::text
             WHERE correlation_id IS NULL OR correlation_id = ''
            """
        )
    if "detected_at" in columns:
        cr.execute(
            """
            UPDATE codestra_data_quality_issue
               SET detected_at = COALESCE(create_date, NOW())
             WHERE detected_at IS NULL
            """
        )
    if {"resolved_at", "state"} <= columns:
        cr.execute(
            """
            UPDATE codestra_data_quality_issue
               SET resolved_at = COALESCE(write_date, create_date, NOW())
             WHERE resolved_at IS NULL
               AND state IN ('resolved', 'ignored')
            """
        )
