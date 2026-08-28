"""Backfill fail-closed telephony intent from existing mapping authority."""

from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    campaigns = env["call.center.campaign"].with_context(active_test=False).search([])
    mappings = env["call.center.campaign.mapping"].with_context(active_test=False).search([])
    by_campaign = {mapping.campaign_id.id: mapping for mapping in mappings}
    for campaign in campaigns:
        mapping = by_campaign.get(campaign.id)
        if not mapping:
            campaign.write({
                "telephony_enabled": False,
                "vicidial_required": False,
                "reconciliation_status": "not_required",
            })
            continue
        prefix = (campaign.business_unit_id.code or "").upper()
        campaign.write({
            "telephony_enabled": True,
            "vicidial_required": True,
            "vicidial_campaign_id": mapping.vicidial_campaign_id,
            "vicidial_user_group": f"{prefix}_AGENTS",
            "vicidial_in_group": (
                f"{mapping.vicidial_campaign_id}I"
                if campaign.direction in ("inbound", "blended") else False
            ),
            "extension_pool": f"{prefix}_PRIMARY",
            "reconciliation_status": "pending",
            "reconciliation_error": False,
        })

    # Preserve semantic Odoo codes while projecting VICIdial-safe identifiers.
    # VICIdial status codes are limited to six characters.
    status_projection = {
        "ANSWERED": "ANS",
        "APPOINTMENT": "APPT",
        "BUSY": "B",
        "DISCONNECTED": "DC",
        "TRANSFER": "XFER",
        "WRONG": "WN",
    }
    dispositions = (
        env["codestra.disposition"]
        .with_context(active_test=False)
        .search([("code", "in", list(status_projection))])
    )
    for disposition in dispositions:
        disposition.vicidial_status_code = status_projection[disposition.code]
