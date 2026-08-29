from odoo import SUPERUSER_ID, api


STATUS_MAP = {
    "ANSWERED": ("human_contact", "status_disposition_contact", True, False, False, "optional"),
    "SALE": ("success", "status_disposition_success", True, False, True, "required"),
    "NOT_INTERESTED": ("negative", "status_disposition_contact", True, False, True, "required"),
    "CALLBACK": ("progress", "status_disposition_contact", True, True, False, "required"),
    "BUSY": ("no_contact", "status_disposition_no_contact", False, False, False, "none"),
    "NO_ANSWER": ("no_contact", "status_disposition_no_contact", False, False, False, "none"),
    "DISCONNECTED": ("invalid_contact", "status_disposition_no_contact", False, False, True, "required"),
    "DNC": ("compliance", "status_disposition_contact", True, False, True, "required"),
    "WRONG_NUMBER": ("invalid_contact", "status_disposition_no_contact", False, False, True, "required"),
}


def post_init_hook(env):
    if not isinstance(env, api.Environment):
        env = api.Environment(env, SUPERUSER_ID, {})
    campaigns = env["call.center.campaign"].with_context(active_test=False).search([("code", "like", "%-R1-STAGING")])
    stage = {
        "SALE": env.ref("codestra_staging_campaign_design.stage_won"),
        "NOT_INTERESTED": env.ref("codestra_staging_campaign_design.stage_lost"),
        "CALLBACK": env.ref("codestra_staging_campaign_design.stage_callback"),
        "DISCONNECTED": env.ref("codestra_staging_campaign_design.stage_lost"),
        "DNC": env.ref("codestra_staging_campaign_design.stage_compliance"),
        "WRONG_NUMBER": env.ref("codestra_staging_campaign_design.stage_lost"),
    }
    model = env["codestra.disposition"].with_context(tracking_disable=True)
    for campaign in campaigns:
        for code, (category, status_xml, human, callback, terminal, policy) in STATUS_MAP.items():
            values = {
                "code": code,
                "name": code.replace("_", " ").title(),
                "business_unit_id": campaign.business_unit_id.id,
                "campaign_id": campaign.id,
                "category": category,
                "vicidial_status_code": code,
                "canonical_status_id": env.ref(f"call_center_core.{status_xml}").id,
                "human_contact": human,
                "callback_required": callback,
                "maximum_retries": 3 if callback else 0,
                "retry_interval_minutes": 60 if callback else 0,
                "terminal": terminal,
                "compliance_block": code == "DNC",
                "note_required": code in {"ANSWERED", "SALE", "NOT_INTERESTED", "CALLBACK", "DNC"},
                "stage_change_policy": policy,
                "allowed_next_stage_ids": [(6, 0, [stage[code].id])] if code in stage else [(5, 0, 0)],
                "active": False,
            }
            existing = model.search([("campaign_id", "=", campaign.id), ("code", "=", code)], limit=1)
            existing.write(values) if existing else model.create(values)


def uninstall_hook(env):
    if not isinstance(env, api.Environment):
        env = api.Environment(env, SUPERUSER_ID, {})
    # Rollback refuses destructive removal after staging evidence is attached.
    profiles = env["codestra.campaign.design.profile"].search([])
    if env["crm.lead"].search_count([("campaign_design_id", "in", profiles.ids)]):
        profiles.write({"active": False})
