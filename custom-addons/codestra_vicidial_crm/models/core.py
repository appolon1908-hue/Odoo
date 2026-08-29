from odoo import api, fields, models
from odoo.exceptions import ValidationError


class Agent(models.Model):
    _name = "codestra.vicidial.agent"
    _description = "VICIdial Agent"
    _order = "name"
    name = fields.Char(required=True)
    vicidial_user = fields.Char(index=True)
    employee_code = fields.Char()
    odoo_user_id = fields.Many2one("res.users")
    tenant_id = fields.Char(required=True, default="COD", index=True)
    phone_login = fields.Char(index=True)
    user_group = fields.Char()
    active = fields.Boolean(default=True)
    status = fields.Selection(
        [
            ("active", "Active (legacy)"),
            ("paused", "Paused (legacy)"),
            ("ready", "Ready"),
            ("ringing", "Ringing"),
            ("on_call", "On Call"),
            ("hold", "Hold"),
            ("wrap_up", "Wrap-up"),
            ("break", "Break"),
            ("lunch", "Lunch"),
            ("training", "Training"),
            ("meeting", "Meeting"),
            ("offline", "Offline"),
        ],
        default="offline",
    )
    campaign_ids = fields.Many2many("codestra.vicidial.campaign")
    supervisor_user_id = fields.Many2one("res.users")
    last_sync_at = fields.Datetime()
    external_updated_at = fields.Datetime()
    sync_state = fields.Selection([("new", "New"), ("synced", "Synced"), ("error", "Error")], default="new")
    notes = fields.Text()
    _vicidial_user_unique = models.Constraint("UNIQUE(vicidial_user)", "VICIdial user must be unique.")
    _phone_login_unique = models.Constraint("UNIQUE(phone_login)", "Phone login must be unique.")


class Campaign(models.Model):
    _name = "codestra.vicidial.campaign"
    _description = "VICIdial Campaign"
    name = fields.Char(string="Campaign Name", required=True)
    campaign_id = fields.Char(string="Campaign ID", required=True, index=True)
    description = fields.Text()
    mode = fields.Selection(
        [
            ("test", "Test / Sandbox Mode"),
            ("canary", "Production Canary"),
            ("production", "Live Production"),
        ],
        default="test",
        required=True,
    )
    active = fields.Boolean(default=True)
    dial_method = fields.Char()
    campaign_type = fields.Char()
    inbound_group = fields.Char()
    allowed_agent_ids = fields.Many2many("codestra.vicidial.agent")
    allowed_disposition_ids = fields.Many2many("codestra.vicidial.disposition", string="Allowed Dispositions")
    supervisor_ids = fields.Many2many("res.users")
    default_disposition_id = fields.Many2one("codestra.vicidial.disposition")
    require_supervisor_transfer_approval = fields.Boolean(default=True)
    max_call_attempts = fields.Integer(default=5)
    wrap_up_timeout_seconds = fields.Integer(default=120)
    sync_enabled = fields.Boolean()
    read_only = fields.Boolean(default=True)
    last_sync_at = fields.Datetime()
    external_updated_at = fields.Datetime()
    _campaign_id_unique = models.Constraint("UNIQUE(campaign_id)", "Campaign ID must be unique.")
    _wrap_up_timeout_nonnegative = models.Constraint(
        "CHECK(wrap_up_timeout_seconds >= 0)", "Wrap-up timeout cannot be negative."
    )


class Phone(models.Model):
    _name = "codestra.vicidial.phone"
    _description = "VICIdial Phone"
    name = fields.Char(required=True)
    extension = fields.Char()
    login = fields.Char(index=True)
    server_ip = fields.Char()
    protocol = fields.Char()
    context = fields.Char()
    active = fields.Boolean(default=True)
    assigned_agent_id = fields.Many2one("codestra.vicidial.agent")
    status = fields.Char()
    last_registration_at = fields.Datetime()


class Disposition(models.Model):
    _name = "codestra.vicidial.disposition"
    _description = "VICIdial Disposition"
    name = fields.Char(string="Display Label", required=True)
    code = fields.Char(string="Disposition Code", required=True, index=True)
    description = fields.Text()
    category = fields.Selection(
        [
            ("positive", "Positive Outcome / Sale"),
            ("contact", "Contact Made / No Sale"),
            ("unreachable", "Unreachable / Line Issue"),
            ("system", "System / Technical Rejection"),
        ],
        default="contact",
        required=True,
    )
    # The installed addon names the campaign model codestra.vicidial.campaign;
    # retain that established model while exposing the requested applicability relation.
    campaign_ids = fields.Many2many("codestra.vicidial.campaign", string="Applicable Campaigns")
    active = fields.Boolean(default=True)
    requires_note = fields.Boolean(default=False)
    requires_callback = fields.Boolean(default=False)
    callback_delay_minutes = fields.Integer()
    closes_lead = fields.Boolean(default=False)
    marks_do_not_call = fields.Boolean(default=False)
    marks_sale = fields.Boolean(default=False)
    sort_order = fields.Integer()
    _code_unique = models.Constraint("UNIQUE(code)", "Disposition code must be unique.")


class Call(models.Model):
    _name = "codestra.vicidial.call"
    _description = "VICIdial Call"
    name = fields.Char(required=True)
    uniqueid = fields.Char(index=True)
    lead_id = fields.Many2one("crm.lead")
    crm_lead_id = fields.Many2one("crm.lead")
    agent_id = fields.Many2one("codestra.vicidial.agent")
    campaign_id = fields.Many2one("codestra.vicidial.campaign")
    phone_id = fields.Many2one("codestra.vicidial.phone")
    direction = fields.Selection([("inbound", "Inbound"), ("outbound", "Outbound")])
    caller_id = fields.Char()
    destination = fields.Char()
    start_at = fields.Datetime()
    answer_at = fields.Datetime()
    end_at = fields.Datetime()
    duration_seconds = fields.Integer()
    billable_seconds = fields.Integer()
    status = fields.Char()
    disposition_id = fields.Many2one("codestra.vicidial.disposition")
    recording_ids = fields.One2many("codestra.vicidial.recording", "call_id")
    transfer_ids = fields.One2many("codestra.vicidial.transfer", "call_id")
    external_call_id = fields.Char()
    source_system = fields.Char()
    raw_event_reference = fields.Char()
    idempotency_key = fields.Char(index=True)
    _uniqueid_unique = models.Constraint("UNIQUE(uniqueid)", "Unique call ID must be unique.")
    _idempotency_unique = models.Constraint("UNIQUE(idempotency_key)", "Idempotency key must be unique.")
    _duration_positive = models.Constraint(
        "CHECK(duration_seconds >= 0 AND billable_seconds >= 0)",
        "Durations cannot be negative.",
    )


class CallEvent(models.Model):
    _name = "codestra.vicidial.call.event"
    _description = "VICIdial Call Event"
    event_type = fields.Char(required=True)
    occurred_at = fields.Datetime()
    call_id = fields.Many2one("codestra.vicidial.call")
    agent_id = fields.Many2one("codestra.vicidial.agent")
    campaign_id = fields.Many2one("codestra.vicidial.campaign")
    payload_json = fields.Text()
    payload_hash = fields.Char(index=True)
    idempotency_key = fields.Char(required=True)
    processing_state = fields.Selection(
        [
            ("new", "New"),
            ("processed", "Processed"),
            ("retry", "Retry"),
            ("failed", "Failed"),
        ],
        default="new",
    )
    processed_at = fields.Datetime()
    retry_count = fields.Integer()
    last_error = fields.Text()
    correlation_id = fields.Char(index=True)
    _event_idempotency_unique = models.Constraint("UNIQUE(idempotency_key)", "Event idempotency key must be unique.")


class Transfer(models.Model):
    _name = "codestra.vicidial.transfer"
    _description = "VICIdial Transfer"
    call_id = fields.Many2one("codestra.vicidial.call", required=True)
    from_agent_id = fields.Many2one("codestra.vicidial.agent")
    to_agent_id = fields.Many2one("codestra.vicidial.agent")
    to_queue = fields.Char()
    transfer_type = fields.Char()
    requested_at = fields.Datetime()
    accepted_at = fields.Datetime()
    completed_at = fields.Datetime()
    status = fields.Char()
    authorized_by_id = fields.Many2one("res.users")
    authorization_reason = fields.Text()
    external_transfer_id = fields.Char(index=True)
    failure_reason = fields.Text()
    _external_transfer_unique = models.Constraint("UNIQUE(external_transfer_id)", "Transfer event must be unique.")


class Recording(models.Model):
    _name = "codestra.vicidial.recording"
    _description = "VICIdial Recording"
    call_id = fields.Many2one("codestra.vicidial.call", required=True)
    recording_id = fields.Char(index=True)
    filename = fields.Char()
    storage_url = fields.Char()
    storage_backend = fields.Char()
    duration_seconds = fields.Integer()
    mime_type = fields.Char()
    checksum_sha256 = fields.Char()
    available = fields.Boolean()
    access_level = fields.Selection([("restricted", "Restricted"), ("permitted", "Permitted")], default="restricted")
    created_at = fields.Datetime()
    expires_at = fields.Datetime()
    _recording_id_unique = models.Constraint("UNIQUE(recording_id)", "Recording metadata must be unique.")


class QueueSnapshot(models.Model):
    _name = "codestra.vicidial.queue.snapshot"
    _description = "VICIdial Queue Snapshot"
    queue_name = fields.Char(required=True)
    campaign_id = fields.Many2one("codestra.vicidial.campaign")
    captured_at = fields.Datetime(default=fields.Datetime.now)
    waiting_calls = fields.Integer()
    available_agents = fields.Integer()
    paused_agents = fields.Integer()
    active_calls = fields.Integer()
    longest_wait_seconds = fields.Integer()
    payload_json = fields.Text()


class IntegrationEvent(models.Model):
    _name = "codestra.integration.event"
    _description = "Codestra Integration Event"
    name = fields.Char(default="New Event")
    event_type = fields.Char(required=True)
    source_system = fields.Char()
    destination_system = fields.Char()
    direction = fields.Char()
    correlation_id = fields.Char(index=True)
    idempotency_key = fields.Char(required=True)
    payload_json = fields.Text()
    payload_hash = fields.Char(index=True)
    state = fields.Selection(
        [
            (x, x.replace("_", " ").title())
            for x in [
                "new",
                "validated",
                "queued",
                "processing",
                "processed",
                "retry",
                "failed",
                "dead_letter",
                "ignored",
            ]
        ],
        default="new",
    )
    retry_count = fields.Integer()
    next_retry_at = fields.Datetime()
    processed_at = fields.Datetime()
    last_error = fields.Text()
    dead_letter_id = fields.Many2one("codestra.integration.dead.letter")
    _event_key_unique = models.Constraint("UNIQUE(idempotency_key)", "Integration idempotency key must be unique.")


class DeadLetter(models.Model):
    _name = "codestra.integration.dead.letter"
    _description = "Codestra Integration Dead Letter"
    event_id = fields.Many2one("codestra.integration.event")
    reason = fields.Text()
    payload_json = fields.Text()
    failed_at = fields.Datetime(default=fields.Datetime.now)
    resolved = fields.Boolean()
    resolved_at = fields.Datetime()
    resolved_by = fields.Many2one("res.users")
    resolution_note = fields.Text()


class Mapping(models.Model):
    _name = "codestra.integration.mapping"
    _description = "Codestra Integration Mapping"
    name = fields.Char(required=True)
    mapping_type = fields.Char(required=True)
    external_id = fields.Char(required=True)
    odoo_model = fields.Char()
    odoo_res_id = fields.Integer()
    source_system = fields.Char(required=True)
    active = fields.Boolean(default=True)
    last_sync_at = fields.Datetime()
    metadata_json = fields.Text()
    _mapping_unique = models.Constraint("UNIQUE(mapping_type,external_id,source_system)", "Mapping already exists.")


class Audit(models.Model):
    _name = "codestra.integration.audit"
    _description = "Codestra Integration Audit"
    _order = "occurred_at desc"
    occurred_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    actor_user_id = fields.Many2one("res.users", readonly=True)
    action = fields.Char(readonly=True)
    model_name = fields.Char(readonly=True)
    record_res_id = fields.Integer(readonly=True)
    source_ip = fields.Char(readonly=True)
    correlation_id = fields.Char(readonly=True)
    before_json = fields.Text(readonly=True)
    after_json = fields.Text(readonly=True)
    success = fields.Boolean(readonly=True)
    error_message = fields.Text(readonly=True)

    @api.ondelete(at_uninstall=False)
    def _no_delete(self):
        if not self.env.is_superuser():
            raise ValidationError("Audit records are append-only.")
