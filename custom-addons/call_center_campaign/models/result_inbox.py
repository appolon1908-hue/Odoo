from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

RESULT_CREATE_CAPABILITY = object()
RESULT_WRITE_CAPABILITY = object()


class CodestraIntegrationResultInbox(models.Model):
    _name = "codestra.integration.result.inbox"
    _description = "Immutable Codestra Integration Result Inbox"
    _order = "received_at desc, id desc"

    name = fields.Char(required=True, readonly=True)
    result_public_id = fields.Char(required=True, index=True, readonly=True)
    schema_version = fields.Char(required=True, readonly=True)
    delivery_id = fields.Char(required=True, index=True, readonly=True)
    event_id = fields.Char(required=True, index=True, readonly=True)
    registration_id = fields.Char(required=True, index=True, readonly=True)
    acknowledgement_id = fields.Char(required=True, index=True, readonly=True)
    correlation_id = fields.Char(required=True, index=True, readonly=True)
    causation_id = fields.Char(index=True, readonly=True)
    workflow_id = fields.Char(required=True, index=True, readonly=True)
    workflow_version = fields.Char(required=True, readonly=True)
    execution_id = fields.Char(required=True, index=True, readonly=True)
    execution_status = fields.Selection(
        [
            ("SUCCEEDED", "Succeeded"),
            ("FAILED", "Failed"),
            ("DEAD_LETTERED", "Dead Lettered"),
        ],
        required=True,
        readonly=True,
    )
    result_classification = fields.Char(required=True, readonly=True)
    result_hash = fields.Char(required=True, size=64, readonly=True)
    organization_public_id = fields.Char(required=True, index=True, readonly=True)
    business_unit_id = fields.Many2one(
        "call.center.business.unit",
        required=True,
        ondelete="restrict",
        index=True,
        readonly=True,
    )
    campaign_id = fields.Many2one(
        "call.center.campaign",
        required=True,
        ondelete="restrict",
        index=True,
        readonly=True,
    )
    source_system = fields.Char(required=True, readonly=True)
    source_environment = fields.Char(required=True, readonly=True)
    policy_hash = fields.Char(required=True, size=64, readonly=True)
    originating_outbox_id = fields.Many2one(
        "codestra.runtime.integration.outbox",
        required=True,
        ondelete="restrict",
        index=True,
        readonly=True,
        help="Required for new results. Empty only for quarantined legacy rows whose outbox was deleted before FK enforcement.",
    )
    originating_outbox_legacy_id = fields.Integer(
        readonly=True,
        index=True,
        help="Preserved pre-migration outbox ID for an orphaned legacy audit result.",
    )
    originating_model = fields.Char(required=True, readonly=True)
    originating_res_id = fields.Integer(required=True, readonly=True)
    received_at = fields.Datetime(required=True, readonly=True)
    acknowledged_at = fields.Datetime(required=True, readonly=True)
    completed_at = fields.Datetime(readonly=True)
    processed_at = fields.Datetime(readonly=True)
    processing_status = fields.Selection(
        [
            ("RECEIVED", "Received"),
            ("PROCESSED", "Processed"),
            ("FAILED", "Failed"),
        ],
        required=True,
        default="RECEIVED",
        readonly=True,
    )
    reconciliation_status = fields.Selection(
        [
            ("RECONCILED", "Reconciled"),
            ("DRIFTED", "Drifted"),
            ("REVIEW_REQUIRED", "Review Required"),
        ],
        required=True,
        readonly=True,
    )
    error_class = fields.Char(readonly=True)
    error_summary = fields.Char(readonly=True)
    payload_json_redacted = fields.Json(required=True, readonly=True)
    request_hash = fields.Char(required=True, size=64, readonly=True)
    created_by_service = fields.Char(required=True, readonly=True)

    _result_public_id_unique = models.Constraint(
        "unique(result_public_id)", "Result public IDs must be unique."
    )
    _acknowledgement_unique = models.Constraint(
        "unique(acknowledgement_id)", "Acknowledgements must be unique."
    )
    _delivery_unique = models.Constraint(
        "unique(delivery_id)",
        "A delivery may have only one authoritative result.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        if (
            self.env.context.get("_codestra_result_capability")
            is not RESULT_CREATE_CAPABILITY
        ):
            raise AccessError("Result inbox records require the callback capability.")
        if any(not values.get("originating_outbox_id") for values in vals_list):
            raise ValidationError("New result inbox records require an originating outbox event.")
        return super().create(vals_list)

    def write(self, vals):
        if (
            self.env.context.get("_codestra_result_capability")
            is not RESULT_WRITE_CAPABILITY
        ):
            raise AccessError("Result inbox state is callback controlled.")
        allowed = {
            "processing_status",
            "processed_at",
            "completed_at",
            "error_class",
            "error_summary",
        }
        if set(vals) - allowed:
            raise ValidationError("Immutable result identity cannot be changed.")
        transitions = {
            "RECEIVED": {"PROCESSED", "FAILED"},
            "PROCESSED": set(),
            "FAILED": set(),
        }
        for record in self:
            if (
                "processing_status" in vals
                and vals["processing_status"]
                not in transitions[record.processing_status]
            ):
                raise ValidationError("Invalid result processing transition.")
        return super().write(vals)

    def unlink(self):
        raise AccessError("Result inbox evidence cannot be deleted.")

    @api.model
    def _create_from_callback(self, vals):
        return self.with_context(
            _codestra_result_capability=RESULT_CREATE_CAPABILITY
        ).create(vals)

    def _mark_processed(self):
        return self.with_context(
            _codestra_result_capability=RESULT_WRITE_CAPABILITY
        ).write(
            {
                "processing_status": "PROCESSED",
                "processed_at": fields.Datetime.now(),
                "completed_at": fields.Datetime.now(),
            }
        )


class CodestraIntegrationCallbackNonce(models.Model):
    _name = "codestra.integration.callback.nonce"
    _description = "Codestra Integration Callback Replay Guard"

    service_id = fields.Char(required=True, readonly=True)
    nonce = fields.Char(required=True, readonly=True)
    expires_at = fields.Datetime(required=True, readonly=True)

    _service_nonce_unique = models.Constraint(
        "unique(service_id, nonce)", "Callback nonces cannot be replayed."
    )

    @api.model
    def _cron_purge_expired(self):
        expired = self.sudo().search([("expires_at", "<", fields.Datetime.now())])
        return expired.unlink()


class CodestraIntegrationTrace(models.Model):
    _name = "codestra.integration.trace"
    _description = "Read-only Codestra Integration Trace"
    _auto = False
    _order = "result_received_at desc"

    correlation_id = fields.Char(readonly=True)
    event_id = fields.Char(readonly=True)
    delivery_id = fields.Char(readonly=True)
    registration_id = fields.Char(readonly=True)
    acknowledgement_id = fields.Char(readonly=True)
    workflow_id = fields.Char(readonly=True)
    workflow_version = fields.Char(readonly=True)
    execution_id = fields.Char(readonly=True)
    business_unit_id = fields.Many2one("call.center.business.unit", readonly=True)
    campaign_id = fields.Many2one("call.center.campaign", readonly=True)
    originating_model = fields.Char(readonly=True)
    originating_res_id = fields.Integer(readonly=True)
    requested_at = fields.Datetime(readonly=True)
    acknowledged_at = fields.Datetime(readonly=True)
    result_received_at = fields.Datetime(readonly=True)
    end_to_end_latency_seconds = fields.Float(readonly=True)
    current_status = fields.Char(readonly=True)
    reconciliation_status = fields.Char(readonly=True)
    safe_error_summary = fields.Char(readonly=True)
    result_inbox_id = fields.Many2one(
        "codestra.integration.result.inbox", readonly=True
    )
    originating_outbox_id = fields.Many2one(
        "codestra.runtime.integration.outbox", readonly=True
    )

    def init(self):
        self.env.cr.execute("DROP VIEW IF EXISTS codestra_integration_trace")
        self.env.cr.execute(
            "SELECT to_regclass('codestra_integration_result_inbox'), "
            "to_regclass('codestra_runtime_integration_outbox')"
        )
        inbox_table, outbox_table = self.env.cr.fetchone()
        if not inbox_table or not outbox_table:
            # During a fresh dependency installation Odoo initializes SQL-view
            # models before every newly declared backing table is materialized.
            # A later registry pass creates the projection once both durable
            # evidence tables exist.
            return
        self.env.cr.execute(
            """
            CREATE VIEW codestra_integration_trace AS
            SELECT result.id,
                   result.correlation_id,
                   result.event_id,
                   result.delivery_id,
                   result.registration_id,
                   result.acknowledgement_id,
                   result.workflow_id,
                   result.workflow_version,
                   result.execution_id,
                   result.business_unit_id,
                   result.campaign_id,
                   result.originating_model,
                   result.originating_res_id,
                   outbox.created_at AS requested_at,
                   result.acknowledged_at,
                   result.received_at AS result_received_at,
                   EXTRACT(EPOCH FROM (result.received_at - outbox.created_at))
                       AS end_to_end_latency_seconds,
                   result.processing_status AS current_status,
                   result.reconciliation_status,
                   result.error_summary AS safe_error_summary,
                   result.id AS result_inbox_id,
                   outbox.id AS originating_outbox_id
              FROM codestra_integration_result_inbox result
              JOIN codestra_runtime_integration_outbox outbox
                ON outbox.id = result.originating_outbox_id
            """
        )

    def create(self, vals):
        raise AccessError("Integration Trace is a read-only projection.")

    def write(self, vals):
        raise AccessError("Integration Trace is a read-only projection.")

    def unlink(self):
        raise AccessError("Integration Trace is a read-only projection.")


class CallCenterCampaignTrace(models.Model):
    _inherit = "call.center.campaign"

    integration_trace_count = fields.Integer(compute="_compute_integration_trace_count")

    def _compute_integration_trace_count(self):
        trace = self.env["codestra.integration.trace"]
        for record in self:
            record.integration_trace_count = trace.search_count(
                [("campaign_id", "=", record.id)]
            )

    def action_view_integration_traces(self):
        self.ensure_one()
        action = self.env.ref("call_center_campaign.action_integration_traces").read()[
            0
        ]
        action["domain"] = [("campaign_id", "=", self.id)]
        return action


class CrmLeadIntegrationTrace(models.Model):
    _inherit = "crm.lead"

    integration_trace_count = fields.Integer(compute="_compute_integration_trace_count")

    def _compute_integration_trace_count(self):
        trace = self.env["codestra.integration.trace"]
        for record in self:
            record.integration_trace_count = trace.search_count(
                [
                    ("originating_model", "=", "crm.lead"),
                    ("originating_res_id", "=", record.id),
                ]
            )

    def action_view_integration_traces(self):
        self.ensure_one()
        action = self.env.ref("call_center_campaign.action_integration_traces").read()[
            0
        ]
        action["domain"] = [
            ("originating_model", "=", "crm.lead"),
            ("originating_res_id", "=", self.id),
        ]
        return action


class ResUsersIntegrationTrace(models.Model):
    _inherit = "res.users"

    integration_trace_count = fields.Integer(compute="_compute_integration_trace_count")

    def _compute_integration_trace_count(self):
        trace = self.env["codestra.integration.trace"]
        for record in self:
            record.integration_trace_count = trace.search_count(
                [("campaign_id.agent_ids", "in", record.id)]
            )

    def action_view_integration_traces(self):
        self.ensure_one()
        action = self.env.ref("call_center_campaign.action_integration_traces").read()[
            0
        ]
        action["domain"] = [("campaign_id.agent_ids", "in", self.id)]
        return action
