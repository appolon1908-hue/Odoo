import json
import uuid

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


AUTO_ALLOCATION_EXCLUDED_EXTENSIONS = frozenset({6101})
PROTECTED_ASSIGNMENT_FIELDS = frozenset(
    {
        "odoo_user_id",
        "primary_campaign_id",
        "campaign_ids",
        "phone_login",
        "supervisor_user_id",
        "incoming_calls_enabled",
        "outgoing_calls_enabled",
        "webrtc_enabled",
    }
)


class Agent(models.Model):
    _name = "codestra.vicidial.agent"
    _description = "VICIdial Agent"
    _order = "name"

    name = fields.Char(required=True)
    vicidial_user = fields.Char(index=True)
    employee_code = fields.Char()
    odoo_user_id = fields.Many2one("res.users", required=True, ondelete="restrict")
    odoo_username = fields.Char(related="odoo_user_id.login", readonly=True)
    odoo_email = fields.Char(related="odoo_user_id.email", readonly=True)
    tenant_id = fields.Char(required=True, default="COD", index=True)

    primary_campaign_id = fields.Many2one(
        "codestra.vicidial.campaign",
        string="Campaign",
        ondelete="restrict",
        index=True,
        help="Primary campaign that owns this agent's extension allocation.",
    )
    campaign_external_id = fields.Char(
        related="primary_campaign_id.campaign_id", string="Campaign ID", readonly=True
    )
    extension_pool_active = fields.Boolean(
        related="primary_campaign_id.extension_pool_active",
        string="Extension Pool Active",
        readonly=True,
    )
    campaign_ids = fields.Many2many("codestra.vicidial.campaign")
    supervisor_user_id = fields.Many2one("res.users", string="Supervisor")

    phone_login = fields.Char(
        string="Odoo Extension",
        required=True,
        index=True,
        copy=False,
        help=(
            "The agent's one assigned extension number. This is separate from the "
            "optional WebRTC browser phone device."
        ),
    )
    incoming_calls_enabled = fields.Boolean(default=True)
    outgoing_calls_enabled = fields.Boolean(default=True)
    webrtc_enabled = fields.Boolean(
        string="WebRTC",
        default=False,
        help=(
            "Super Admin opt-in for the browser phone. The extension remains assigned "
            "even when WebRTC is disabled."
        ),
    )
    webrtc_device_limit = fields.Integer(default=1, readonly=True)
    webrtc_device_count = fields.Integer(compute="_compute_webrtc_projection")
    webrtc_status = fields.Selection(
        [
            ("disabled", "Disabled"),
            ("pending", "Enabled / Endpoint Pending"),
            ("provisioned", "Provisioned / Not Registered"),
            ("registered", "Registered"),
            ("conflict", "Conflict"),
        ],
        compute="_compute_webrtc_projection",
    )

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
    last_sync_at = fields.Datetime()
    external_updated_at = fields.Datetime()
    sync_state = fields.Selection(
        [("new", "New"), ("synced", "Synced"), ("error", "Error")],
        default="new",
    )
    notes = fields.Text()

    _vicidial_user_unique = models.Constraint(
        "UNIQUE(vicidial_user)", "VICIdial user must be unique."
    )
    _phone_login_unique = models.Constraint(
        "UNIQUE(phone_login)", "An Odoo extension may belong to only one agent."
    )
    _odoo_user_unique = models.Constraint(
        "UNIQUE(odoo_user_id)", "An Odoo user may have only one telephony agent profile."
    )
    _webrtc_device_limit_one = models.Constraint(
        "CHECK(webrtc_device_limit = 1)", "WebRTC device limit must remain one."
    )

    @api.model
    def _is_telephony_super_admin(self):
        return bool(self.env.su or self.env.user.has_group("base.group_system"))

    @api.model
    def _campaign_ids_from_commands(self, commands):
        values = []
        for command in commands or []:
            try:
                operation = command[0]
            except (TypeError, IndexError):
                continue
            if operation == 6:
                values = list(command[2] or [])
            elif operation == 4:
                values.append(command[1])
            elif operation in {2, 3}:
                values = [value for value in values if value != command[1]]
            elif operation == 5:
                values = []
        return list(dict.fromkeys(int(value) for value in values if value))

    @api.model
    def _allocate_extension_for_campaign(self, campaign, exclude_agent_id=0):
        if not campaign or not campaign.exists():
            raise UserError("A primary campaign is required before allocating an extension.")
        if not campaign.extension_pool_active:
            raise UserError(
                "The campaign has no verified active extension pool. Configure the pool before assigning agents."
            )
        # Lock the campaign row itself: this module owns and allocates from its
        # own extension_range_start/end fields directly, rather than a separate
        # pool model in another addon. codestra_vicidial_crm sits upstream of
        # codestra_identity_provisioning in the module dependency graph (via
        # call_center_campaign -> codestra_integration_hub ->
        # codestra_vicidial_crm), so it cannot depend on that module's
        # codestra.extension.pool/codestra.extension.assignment without a
        # circular dependency; allocation here is self-contained and only
        # checks this module's own tables.
        self.env.cr.execute(
            "SELECT id FROM codestra_vicidial_campaign WHERE id = %s FOR UPDATE",
            [campaign.id],
        )
        self.env.cr.execute(
            """
            SELECT candidate
              FROM generate_series(%s, %s) AS candidate
             WHERE candidate <> ALL(%s)
               AND NOT EXISTS (
                    SELECT 1
                      FROM codestra_vicidial_agent agent
                     WHERE agent.id <> %s
                       AND agent.phone_login = candidate::varchar
               )
               AND NOT EXISTS (
                    SELECT 1
                      FROM codestra_vicidial_phone phone
                     WHERE phone.extension = candidate::varchar
                       AND phone.active IS TRUE
               )
             ORDER BY candidate
             LIMIT 1
            """,
            [
                campaign.extension_range_start,
                campaign.extension_range_end,
                list(AUTO_ALLOCATION_EXCLUDED_EXTENSIONS),
                int(exclude_agent_id or 0),
            ],
        )
        row = self.env.cr.fetchone()
        if not row:
            raise UserError("The campaign extension pool is exhausted.")
        return str(row[0])

    @api.model_create_multi
    def create(self, vals_list):
        normalized = []
        for raw_values in vals_list:
            values = dict(raw_values)
            campaign_ids = self._campaign_ids_from_commands(values.get("campaign_ids"))
            primary_id = int(values.get("primary_campaign_id") or 0)
            if not primary_id and len(campaign_ids) == 1:
                primary_id = campaign_ids[0]
                values["primary_campaign_id"] = primary_id
            if not primary_id:
                raise ValidationError("Every agent must have exactly one primary campaign.")
            if primary_id not in campaign_ids:
                values["campaign_ids"] = list(values.get("campaign_ids") or []) + [(4, primary_id)]
            if not values.get("odoo_user_id"):
                raise ValidationError("Every telephony agent must be assigned to one Odoo user.")
            if self.sudo().search_count([("odoo_user_id", "=", values["odoo_user_id"])]):
                raise ValidationError("An Odoo user may have only one telephony agent profile.")
            extension = str(values.get("phone_login") or "").strip()
            if not extension:
                extension = self._allocate_extension_for_campaign(
                    self.env["codestra.vicidial.campaign"].browse(primary_id)
                )
                values["phone_login"] = extension
            else:
                values["phone_login"] = extension
            if self.sudo().search_count([("phone_login", "=", extension)]):
                raise ValidationError("An Odoo extension may belong to only one agent.")
            normalized.append(values)
        records = super().create(normalized)
        for record in records.filtered("webrtc_enabled"):
            record._queue_telephony_assignment_event("telephony.webrtc.enable")
        return records

    @api.depends("webrtc_enabled", "phone_login")
    def _compute_webrtc_projection(self):
        phones = self.env["codestra.vicidial.phone"].sudo().search(
            [("assigned_agent_id", "in", self.ids), ("active", "=", True)]
        ) if self.ids else self.env["codestra.vicidial.phone"]
        by_agent = {}
        for phone in phones:
            by_agent.setdefault(phone.assigned_agent_id.id, []).append(phone)
        registered_states = {"REGISTERED", "REACHABLE", "AVAILABLE", "OK"}
        for record in self:
            assigned = by_agent.get(record.id, [])
            record.webrtc_device_count = len(assigned)
            if not record.webrtc_enabled:
                record.webrtc_status = "disabled"
            elif not assigned:
                record.webrtc_status = "pending"
            elif len(assigned) > 1:
                record.webrtc_status = "conflict"
            elif str(assigned[0].status or "").upper() in registered_states:
                record.webrtc_status = "registered"
            else:
                record.webrtc_status = "provisioned"

    @api.constrains(
        "phone_login",
        "odoo_user_id",
        "primary_campaign_id",
        "campaign_ids",
        "supervisor_user_id",
        "webrtc_device_limit",
    )
    def _check_telephony_assignment(self):
        for record in self:
            if not record.odoo_user_id:
                raise ValidationError("Every telephony agent must be assigned to one Odoo user.")
            if not (record.phone_login or "").strip():
                raise ValidationError("Every agent must have exactly one Odoo extension.")
            if not record.primary_campaign_id:
                raise ValidationError("Every agent must have a primary campaign.")
            if record.primary_campaign_id not in record.campaign_ids:
                raise ValidationError("The primary campaign must be authorized for the agent.")
            if record.supervisor_user_id and record.primary_campaign_id.supervisor_ids:
                if record.supervisor_user_id not in record.primary_campaign_id.supervisor_ids:
                    raise ValidationError("The supervisor is not assigned to this campaign.")
            if record.webrtc_device_limit != 1:
                raise ValidationError("Each agent may have only one WebRTC endpoint.")
            duplicate_user = self.search_count(
                [("id", "!=", record.id), ("odoo_user_id", "=", record.odoo_user_id.id)]
            )
            if duplicate_user:
                raise ValidationError("An Odoo user may have only one telephony agent profile.")
            duplicate_extension = self.search_count(
                [("id", "!=", record.id), ("phone_login", "=", record.phone_login)]
            )
            if duplicate_extension:
                raise ValidationError("An Odoo extension may belong to only one agent.")

    def _assignment_payload(self, **extra):
        self.ensure_one()
        payload = {
            "agent_record_id": self.id,
            "odoo_user_id": self.odoo_user_id.id,
            "keycloak_subject": self.odoo_user_id.keycloak_subject or None,
            "tenant_id": self.tenant_id,
            "vicidial_user": self.vicidial_user,
            "campaign_id": self.primary_campaign_id.campaign_id,
            "extension": self.phone_login,
            "supervisor_user_id": self.supervisor_user_id.id or None,
            "incoming_calls_enabled": bool(self.incoming_calls_enabled),
            "outgoing_calls_enabled": bool(self.outgoing_calls_enabled),
            "webrtc_enabled": bool(self.webrtc_enabled),
            "webrtc_device_limit": 1,
        }
        payload.update(extra)
        return payload

    def _queue_telephony_assignment_event(self, event_type, **extra):
        self.ensure_one()
        if self.env.context.get("skip_telephony_assignment_events"):
            return self.env["codestra.integration.event"]
        correlation = "telephony-assignment-" + str(uuid.uuid4())
        return self.env["codestra.integration.event"].sudo().create(
            {
                "name": event_type,
                "event_type": event_type,
                "source_system": "odoo",
                "destination_system": "middleware",
                "direction": "outbound",
                "correlation_id": correlation,
                "idempotency_key": event_type + ":" + str(self.id) + ":" + str(uuid.uuid4()),
                "payload_json": json.dumps(self._assignment_payload(**extra), sort_keys=True),
                "state": "queued",
            }
        )

    def write(self, values):
        protected = PROTECTED_ASSIGNMENT_FIELDS.intersection(values)
        if protected and not self._is_telephony_super_admin():
            raise AccessError(
                "Only a Super Admin may change telephony assignment, campaign, supervisor, or WebRTC settings."
            )
        if "campaign_ids" in values and "primary_campaign_id" not in values and not self.env.context.get(
            "telephony_assignment_internal"
        ):
            raise AccessError("Change the primary Campaign instead of editing campaign membership directly.")
        if "phone_login" in values and not self.env.context.get("telephony_assignment_internal"):
            raise AccessError("Use Replace Extension; Odoo extensions are automatically allocated.")

        before = {
            record.id: {
                "extension": record.phone_login,
                "webrtc_enabled": record.webrtc_enabled,
                "incoming": record.incoming_calls_enabled,
                "outgoing": record.outgoing_calls_enabled,
                "campaign_id": record.primary_campaign_id.id,
            }
            for record in self
        }
        replacement = {}
        mutable_values = dict(values)
        if "primary_campaign_id" in mutable_values and not self.env.context.get(
            "telephony_assignment_internal"
        ):
            self.ensure_one()
            campaign = self.env["codestra.vicidial.campaign"].browse(
                int(mutable_values["primary_campaign_id"])
            ).exists()
            if not campaign:
                raise ValidationError("Campaign is unavailable.")
            old_extension = self.phone_login
            new_extension = self._allocate_extension_for_campaign(campaign, self.id)
            mutable_values["phone_login"] = new_extension
            mutable_values["campaign_ids"] = [(6, 0, [campaign.id])]
            replacement[self.id] = (old_extension, new_extension)

        result = super().write(mutable_values)

        for record in self:
            previous = before[record.id]
            if record.id in replacement:
                old_extension, new_extension = replacement[record.id]
                record._release_projected_extension(old_extension)
                record._queue_telephony_assignment_event(
                    "telephony.extension.replace",
                    old_extension=old_extension,
                    new_extension=new_extension,
                    sequence=["revoke_old_endpoint", "release_old_extension", "provision_new_assignment"],
                )
            if "webrtc_enabled" in mutable_values and previous["webrtc_enabled"] != record.webrtc_enabled:
                if record.webrtc_enabled:
                    record._queue_telephony_assignment_event("telephony.webrtc.enable")
                else:
                    record._release_projected_webrtc()
                    record._queue_telephony_assignment_event("telephony.webrtc.disable")
            if {"incoming_calls_enabled", "outgoing_calls_enabled"}.intersection(mutable_values) and (
                previous["incoming"] != record.incoming_calls_enabled
                or previous["outgoing"] != record.outgoing_calls_enabled
            ):
                record._queue_telephony_assignment_event("telephony.call_permissions.update")
        return result

    def _release_projected_webrtc(self):
        for record in self:
            phones = self.env["codestra.vicidial.phone"].sudo().search(
                [("assigned_agent_id", "=", record.id), ("active", "=", True)]
            )
            if phones:
                phones.write({"active": False, "status": "REVOCATION_PENDING"})

    def _release_projected_extension(self, extension):
        self.ensure_one()
        if extension:
            phones = self.env["codestra.vicidial.phone"].sudo().search(
                [
                    ("assigned_agent_id", "=", self.id),
                    ("extension", "=", extension),
                    ("active", "=", True),
                ]
            )
            if phones:
                phones.write({"active": False, "status": "REPLACEMENT_PENDING"})

    def action_replace_extension(self):
        if not self._is_telephony_super_admin():
            raise AccessError("Only a Super Admin may replace an extension.")
        for record in self:
            old_extension = record.phone_login
            new_extension = record._allocate_extension_for_campaign(
                record.primary_campaign_id, record.id
            )
            record._release_projected_extension(old_extension)
            record.with_context(telephony_assignment_internal=True).write(
                {"phone_login": new_extension}
            )
            record._queue_telephony_assignment_event(
                "telephony.extension.replace",
                old_extension=old_extension,
                new_extension=new_extension,
                sequence=["revoke_old_endpoint", "release_old_extension", "provision_new_assignment"],
            )
        return True

    def action_revoke_webrtc_credentials(self):
        if not self._is_telephony_super_admin():
            raise AccessError("Only a Super Admin may revoke WebRTC credentials.")
        for record in self:
            record._queue_telephony_assignment_event("telephony.webrtc.revoke_credentials")
        return True


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
    extension_range_start = fields.Integer(
        string="Extension Range Start",
        help="Lowest extension Odoo may auto-allocate for this campaign's agents.",
    )
    extension_range_end = fields.Integer(
        string="Extension Range End",
        help="Highest extension Odoo may auto-allocate for this campaign's agents.",
    )
    extension_pool_active = fields.Boolean(
        string="Extension Pool Active",
        default=False,
        help="Verified pool used by Odoo to allocate one extension per agent.",
    )
    allowed_agent_ids = fields.Many2many("codestra.vicidial.agent")
    allowed_disposition_ids = fields.Many2many(
        "codestra.vicidial.disposition", string="Allowed Dispositions"
    )
    supervisor_ids = fields.Many2many("res.users")
    default_disposition_id = fields.Many2one("codestra.vicidial.disposition")
    require_supervisor_transfer_approval = fields.Boolean(default=True)
    max_call_attempts = fields.Integer(default=5)
    wrap_up_timeout_seconds = fields.Integer(default=120)
    sync_enabled = fields.Boolean()
    read_only = fields.Boolean(default=True)
    last_sync_at = fields.Datetime()
    external_updated_at = fields.Datetime()

    _campaign_id_unique = models.Constraint(
        "UNIQUE(campaign_id)", "Campaign ID must be unique."
    )
    _wrap_up_timeout_nonnegative = models.Constraint(
        "CHECK(wrap_up_timeout_seconds >= 0)", "Wrap-up timeout cannot be negative."
    )

    _EXTENSION_POOL_FIELDS = frozenset(
        {"extension_range_start", "extension_range_end", "extension_pool_active"}
    )

    @api.model_create_multi
    def create(self, vals_list):
        if any(
            self._EXTENSION_POOL_FIELDS.intersection(values) for values in vals_list
        ) and not (self.env.su or self.env.user.has_group("base.group_system")):
            raise AccessError("Only a Super Admin may assign a campaign extension pool.")
        return super().create(vals_list)

    def write(self, values):
        if self._EXTENSION_POOL_FIELDS.intersection(values) and not (
            self.env.su or self.env.user.has_group("base.group_system")
        ):
            raise AccessError("Only a Super Admin may change a campaign extension pool.")
        return super().write(values)

    @api.constrains("extension_pool_active", "extension_range_start", "extension_range_end")
    def _check_extension_pool_range(self):
        for campaign in self:
            if not campaign.extension_pool_active:
                continue
            if campaign.extension_range_start <= 0 or campaign.extension_range_end <= 0:
                raise ValidationError(
                    "An active extension pool requires a positive extension range."
                )
            if campaign.extension_range_start > campaign.extension_range_end:
                raise ValidationError("The extension range start must not exceed its end.")


class Phone(models.Model):
    _name = "codestra.vicidial.phone"
    _description = "VICIdial Phone"

    name = fields.Char(required=True)
    extension = fields.Char(required=True)
    login = fields.Char(index=True)
    server_ip = fields.Char()
    protocol = fields.Char()
    context = fields.Char()
    active = fields.Boolean(default=True)
    assigned_agent_id = fields.Many2one(
        "codestra.vicidial.agent", required=True, ondelete="restrict"
    )
    status = fields.Char()
    last_registration_at = fields.Datetime()

    _extension_unique = models.Constraint(
        "UNIQUE(extension)", "A WebRTC endpoint extension may have only one Odoo phone projection."
    )
    _assigned_agent_unique = models.Constraint(
        "UNIQUE(assigned_agent_id)", "An agent may have only one WebRTC endpoint."
    )

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            agent_id = values.get("assigned_agent_id")
            extension = str(values.get("extension") or "").strip()
            if not agent_id or not extension:
                raise ValidationError("A WebRTC phone projection requires an agent and extension.")
            agent = self.env["codestra.vicidial.agent"].browse(int(agent_id)).exists()
            if not agent:
                raise ValidationError("The WebRTC agent assignment is unavailable.")
            if extension != agent.phone_login:
                raise ValidationError("The WebRTC endpoint must use the agent's Odoo extension.")
            if values.get("active", True) and not agent.webrtc_enabled:
                raise ValidationError("WebRTC is disabled for this agent.")
            if self.search_count([("assigned_agent_id", "=", agent.id)]):
                raise ValidationError("An agent may have only one WebRTC endpoint.")
            if self.search_count([("extension", "=", extension)]):
                raise ValidationError("A WebRTC endpoint extension may belong to only one agent.")
        return super().create(vals_list)

    @api.constrains("extension", "assigned_agent_id", "active")
    def _check_agent_endpoint_binding(self):
        for record in self:
            if record.extension != record.assigned_agent_id.phone_login:
                raise ValidationError("The WebRTC endpoint must match the agent's Odoo extension.")
            if record.active and not record.assigned_agent_id.webrtc_enabled:
                raise ValidationError("An active WebRTC endpoint requires WebRTC to be enabled in Odoo.")

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

    @api.model
    def _append(
        self,
        event,
        action,
        result,
        metadata,
        *,
        actor_role=None,
        correlation_id=None,
        subject_model=None,
        subject_id=None,
    ):
        """Append through one contract whether or not Integration Hub is installed."""
        if not isinstance(metadata, dict):
            raise ValidationError("Audit metadata must be an object.")
        if actor_role not in {
            None,
            "system",
            "user",
            "agent",
            "supervisor",
            "qa",
            "admin",
            "service",
        }:
            raise ValidationError("Audit actor role is invalid.")

        if event:
            event.ensure_one()
            event = event.exists()
            if not event:
                raise ValidationError("Audit event anchor is unavailable.")
            if correlation_id and event.correlation_id != correlation_id:
                raise ValidationError("Audit correlation does not match the event anchor.")
            correlation_id = event.correlation_id

        subject_model = subject_model or metadata.get("model_name")
        subject_id = subject_id or metadata.get("record_res_id")
        correlation_id = (correlation_id or "").strip()
        if not correlation_id or not subject_model or not subject_id:
            raise ValidationError("Audit correlation and subject are required.")

        after = metadata.get("after", metadata)
        return self.sudo().create(
            {
                "actor_user_id": self.env.user.id,
                "action": action,
                "model_name": subject_model,
                "record_res_id": int(subject_id),
                "correlation_id": correlation_id,
                "after_json": json.dumps(after, sort_keys=True, default=str),
                "success": result == "success",
                "error_message": metadata.get("error_message") if result != "success" else False,
            }
        )

    @api.ondelete(at_uninstall=False)
    def _no_delete(self):
        if not self.env.is_superuser():
            raise ValidationError("Audit records are append-only.")
