from odoo import api, models

from .automatic_provisioning_common import DESIGN_REQUEST_EVENT

class CodestraIntegrationOutboxAutomaticProvisioning(models.Model):
    _inherit = "codestra.runtime.integration.outbox"

    @api.model
    def _claim_batch(
        self,
        limit=20,
        consumer_id=None,
        lease_ttl_seconds=30,
        record_environment=None,
        business_unit_codes=None,
        event_type_allowlist=None,
    ):
        if event_type_allowlist is None:
            event_type_allowlist = self.env.context.get(
                "_codestra_cron_event_type_allowlist"
            )
        return super()._claim_batch(
            limit=limit,
            consumer_id=consumer_id,
            lease_ttl_seconds=lease_ttl_seconds,
            record_environment=record_environment,
            business_unit_codes=business_unit_codes,
            event_type_allowlist=event_type_allowlist,
        )

    @api.model
    def _cron_deliver_campaign_design_events(self):
        return super(
            CodestraIntegrationOutboxAutomaticProvisioning,
            self.with_context(
                _codestra_cron_event_type_allowlist=[DESIGN_REQUEST_EVENT]
            ),
        )._cron_deliver_campaign_design_events()

    def _finalize_delivery_success(self, result):
        self.ensure_one()
        if self.event_type == DESIGN_REQUEST_EVENT:
            revision = self.campaign_id._ensure_revision_record(
                self,
                self.payload_json.get("validation", {}).get("errors", []),
            )
            revision._record_preview(result)
        return super()._finalize_delivery_success(result)
