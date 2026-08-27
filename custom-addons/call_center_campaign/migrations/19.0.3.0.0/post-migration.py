def migrate(cr, version):
    mappings = {
        "stage_validating": "status_journey_validation",
        "stage_ready_ai": "status_journey_qualification",
        "stage_ai_progress": "status_journey_qualification",
        "stage_ai_qualified": "status_journey_qualification",
        "stage_human_required": "status_journey_qualification",
        "stage_callback": "status_journey_engaged",
        "stage_closer": "status_journey_engaged",
        "stage_fulfillment": "status_journey_converted",
        "stage_retention": "status_journey_retention",
        "stage_upsell": "status_journey_retention",
        "stage_do_not_contact": "status_journey_blocked",
    }
    for stage_xmlid, status_xmlid in mappings.items():
        cr.execute(
            """
            UPDATE crm_stage
               SET canonical_journey_status_id = status_data.res_id
              FROM ir_model_data stage_data, ir_model_data status_data
             WHERE stage_data.module = 'call_center_campaign'
               AND stage_data.name = %s
               AND stage_data.model = 'crm.stage'
               AND status_data.module = 'call_center_core'
               AND status_data.name = %s
               AND status_data.model = 'call.center.canonical.status'
               AND crm_stage.id = stage_data.res_id
            """,
            (stage_xmlid, status_xmlid),
        )
