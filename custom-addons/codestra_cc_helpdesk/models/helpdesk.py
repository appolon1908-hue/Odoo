import json
import uuid
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


SLA_WRITE_CAPABILITY = object()
TICKET_WORKFLOW_CAPABILITY = object()
TICKET_IMPORT_CAPABILITY = object()
OPERATIONAL_GROUPS = (
    "codestra_cc_security.group_cc_campaign_agent",
    "codestra_cc_security.group_cc_senior_agent",
    "codestra_cc_security.group_cc_campaign_supervisor",
)
FORBIDDEN_TEXT_PATTERNS = (
    "card number",
    "security code",
    "cvv",
    "bank password",
    "api key",
    "access token",
)


def _is_operational(user):
    return any(user.has_group(xmlid) for xmlid in OPERATIONAL_GROUPS)


def _is_global_admin(user):
    return user.has_group("codestra_cc_security.group_cc_global_administrator")


def _is_supervisor(user):
    return user.has_group("codestra_cc_security.group_cc_campaign_supervisor")


def _ticket_campaign(env, supplied_campaign_id=False, profile=False, queue=False):
    candidates = (profile.campaign_id if profile else env["cc.campaign"]) | (
        queue.campaign_id if queue else env["cc.campaign"]
    )
    if len(candidates) > 1:
        raise ValidationError(_("Ticket profile and queue campaigns differ."))
    if _is_operational(env.user):
        campaign = env.user._cc_resolve_operational_membership().campaign_id
        if supplied_campaign_id and supplied_campaign_id != campaign.id:
            raise AccessError(_("The authenticated membership determines ticket scope."))
        if candidates and candidates != campaign:
            raise AccessError(_("Ticket resources belong to another campaign."))
        return campaign
    if candidates:
        if supplied_campaign_id and supplied_campaign_id != candidates.id:
            raise ValidationError(_("Ticket resource and campaign scope differ."))
        return candidates
    campaign = env["cc.campaign"].browse(supplied_campaign_id).exists()
    if not campaign:
        raise ValidationError(_("A canonical ticket campaign is required."))
    campaign.check_access("read")
    return campaign


class CcCustomerProfile(models.Model):
    _inherit = "cc.customer.profile"

    helpdesk_ticket_ids = fields.One2many(
        "cc.helpdesk.ticket", "customer_profile_id", readonly=True
    )

    def action_open_tickets(self):
        self.ensure_one()
        self.check_access("read")
        return {
            "type": "ir.actions.act_window",
            "name": _("Campaign Helpdesk"),
            "res_model": "cc.helpdesk.ticket",
            "view_mode": "list,form",
            "domain": [("customer_profile_id", "=", self.id)],
            "context": {"default_customer_profile_id": self.id},
        }


class CcHelpdeskQueue(models.Model):
    _name = "cc.helpdesk.queue"
    _description = "Campaign Helpdesk Queue"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "campaign_id, name"

    name = fields.Char(required=True)
    queue_key = fields.Char(required=True, index=True)
    environment = fields.Selection(
        related="campaign_id.environment", store=True, readonly=True, index=True
    )
    active = fields.Boolean(default=True, required=True, index=True)
    ticket_ids = fields.One2many("cc.helpdesk.ticket", "queue_id", readonly=True)
    sla_policy_ids = fields.One2many(
        "cc.helpdesk.sla.policy", "queue_id", readonly=True
    )

    _queue_key_unique = models.Constraint(
        "unique(campaign_id, queue_key)",
        "Helpdesk queue keys must be unique inside a campaign.",
    )

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            key = (values.get("queue_key") or "").strip().lower()
            if not key or key != values.get("queue_key"):
                raise ValidationError(_("Queue keys must be normalized lowercase."))
        return super().create(values_list)

    def write(self, values):
        if {"campaign_id", "queue_key"}.intersection(values):
            raise AccessError(_("Helpdesk queue ownership is immutable."))
        return super().write(values)

    def unlink(self):
        if any(queue.ticket_ids or queue.sla_policy_ids for queue in self):
            raise AccessError(_("Used helpdesk queues are retained."))
        return super().unlink()


class CcHelpdeskSlaPolicy(models.Model):
    _name = "cc.helpdesk.sla.policy"
    _description = "Governed Campaign Helpdesk SLA"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "campaign_id, queue_id, priority desc, version desc"

    name = fields.Char(required=True)
    policy_uuid = fields.Char(
        required=True,
        default=lambda self: str(uuid.uuid4()),
        readonly=True,
        copy=False,
        index=True,
    )
    queue_id = fields.Many2one(
        "cc.helpdesk.queue", required=True, ondelete="restrict", index=True
    )
    priority = fields.Selection(
        [("0", "Low"), ("1", "Normal"), ("2", "High"), ("3", "Urgent")],
        required=True,
        default="1",
        index=True,
    )
    version = fields.Integer(required=True, default=1)
    first_response_minutes = fields.Integer(required=True, default=60)
    resolution_minutes = fields.Integer(required=True, default=480)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("pending_approval", "Pending Approval"),
            ("approved", "Approved"),
            ("retired", "Retired"),
        ],
        required=True,
        default="draft",
        copy=False,
        index=True,
    )
    requested_by_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user, ondelete="restrict"
    )
    source_ticket = fields.Char(required=True, copy=False, index=True)
    approved_by_id = fields.Many2one(
        "res.users", readonly=True, copy=False, ondelete="restrict"
    )
    approved_at = fields.Datetime(readonly=True, copy=False)

    _policy_uuid_unique = models.Constraint(
        "unique(policy_uuid)", "Helpdesk SLA policy UUIDs must be unique."
    )
    _policy_version_unique = models.Constraint(
        "unique(queue_id, priority, version)",
        "Helpdesk SLA versions must be unique by queue and priority.",
    )
    _one_approved_queue_priority = models.UniqueIndex(
        "(queue_id, priority) WHERE state = 'approved'",
        "A queue may have only one approved SLA per priority.",
    )
    _positive_durations = models.Constraint(
        "check(first_response_minutes > 0 AND resolution_minutes > 0 "
        "AND resolution_minutes >= first_response_minutes)",
        "SLA durations must be positive and resolution cannot precede response.",
    )

    @api.model_create_multi
    def create(self, values_list):
        prepared = []
        for original in values_list:
            values = dict(original)
            if values.get("state", "draft") != "draft":
                raise AccessError(_("SLA policies must begin as drafts."))
            if values.get("requested_by_id") not in (None, self.env.user.id):
                raise AccessError(_("SLA requesters cannot be supplied by another user."))
            values["requested_by_id"] = self.env.user.id
            prepared.append(values)
        records = super().create(prepared)
        records._check_queue_scope()
        return records

    def write(self, values):
        protected = {
            "campaign_id",
            "queue_id",
            "priority",
            "version",
            "state",
            "approved_by_id",
            "approved_at",
            "requested_by_id",
            "source_ticket",
        }
        if protected.intersection(values) and self.env.context.get(
            "_cc_sla_write_capability"
        ) is not SLA_WRITE_CAPABILITY:
            raise AccessError(_("SLA policy state and ownership require governance."))
        editable_draft = {
            "name",
            "first_response_minutes",
            "resolution_minutes",
        }
        if editable_draft.intersection(values):
            if any(policy.state != "draft" for policy in self):
                raise AccessError(_("Submitted SLA versions are immutable."))
            if any(policy.requested_by_id != self.env.user for policy in self):
                raise AccessError(_("Only the SLA requester may edit its draft."))
        result = super().write(values)
        self._check_queue_scope()
        return result

    def unlink(self):
        if any(policy.state != "draft" for policy in self):
            raise AccessError(_("Submitted SLA evidence is retained."))
        if any(policy.requested_by_id != self.env.user for policy in self):
            raise AccessError(_("Only the SLA requester may discard its draft."))
        return super().unlink()

    @api.constrains("queue_id", "campaign_id")
    def _check_queue_scope(self):
        for policy in self:
            if policy.queue_id.campaign_id != policy.campaign_id:
                raise ValidationError(_("SLA policy and queue campaigns differ."))

    def action_submit(self):
        if not self.env.user.has_group(
            "codestra_cc_security.group_cc_campaign_configuration_manager"
        ) and not _is_global_admin(self.env.user):
            raise AccessError(_("Campaign configuration permission is required."))
        for policy in self:
            if policy.state != "draft":
                raise ValidationError(_("Only draft SLA policies can be submitted."))
            if policy.requested_by_id != self.env.user:
                raise AccessError(_("Only the SLA requester may submit this version."))
            policy.with_context(_cc_sla_write_capability=SLA_WRITE_CAPABILITY).write(
                {"state": "pending_approval"}
            )
        return True

    def action_approve(self):
        if not _is_global_admin(self.env.user):
            raise AccessError(_("Global contact-center approval is required."))
        for policy in self:
            if policy.state != "pending_approval":
                raise ValidationError(_("Only submitted SLA policies can be approved."))
            if policy.requested_by_id == self.env.user:
                raise AccessError(_("The SLA requester cannot approve the same version."))
            policy.with_context(_cc_sla_write_capability=SLA_WRITE_CAPABILITY).write(
                {
                    "state": "approved",
                    "approved_by_id": self.env.user.id,
                    "approved_at": fields.Datetime.now(),
                }
            )
            policy.campaign_id.write(
                {"scope_version": policy.campaign_id.scope_version + 1}
            )
        return True

    def action_retire(self):
        if not _is_global_admin(self.env.user):
            raise AccessError(_("Global contact-center approval is required."))
        for policy in self:
            if policy.state != "approved":
                raise ValidationError(_("Only an approved SLA version may be retired."))
            policy.with_context(_cc_sla_write_capability=SLA_WRITE_CAPABILITY).write(
                {"state": "retired"}
            )
            policy.campaign_id.write(
                {"scope_version": policy.campaign_id.scope_version + 1}
            )
        return True


class CcHelpdeskTicket(models.Model):
    _name = "cc.helpdesk.ticket"
    _description = "Campaign-Scoped Helpdesk Ticket"
    _inherit = ["cc.campaign.scoped.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "priority desc, opened_at desc, id desc"
    _rec_name = "ticket_number"

    ticket_uuid = fields.Char(
        required=True,
        default=lambda self: str(uuid.uuid4()),
        readonly=True,
        copy=False,
        index=True,
    )
    ticket_number = fields.Char(
        required=True, readonly=True, copy=False, default="New", index=True
    )
    integration_key = fields.Char(
        required=True,
        default=lambda self: str(uuid.uuid4()),
        readonly=True,
        copy=False,
        index=True,
    )
    environment = fields.Selection(
        related="campaign_id.environment", store=True, readonly=True, index=True
    )
    active = fields.Boolean(default=True, required=True, index=True)
    queue_id = fields.Many2one(
        "cc.helpdesk.queue", required=True, ondelete="restrict", index=True
    )
    customer_profile_id = fields.Many2one(
        "cc.customer.profile", required=True, ondelete="restrict", index=True
    )
    crm_lead_id = fields.Many2one("crm.lead", ondelete="restrict", index=True)
    mail_thread_id = fields.Many2one("cc.mail.thread", ondelete="restrict", index=True)
    subject = fields.Char(required=True, tracking=True, index=True)
    description = fields.Text()
    category = fields.Selection(
        [
            ("support", "Support"),
            ("complaint", "Complaint"),
            ("billing", "Billing"),
            ("documents", "Documents"),
            ("technical", "Technical"),
            ("escalation", "Escalation"),
        ],
        required=True,
        default="support",
        tracking=True,
        index=True,
    )
    priority = fields.Selection(
        [("0", "Low"), ("1", "Normal"), ("2", "High"), ("3", "Urgent")],
        required=True,
        default="1",
        tracking=True,
        index=True,
    )
    severity = fields.Selection(
        [("low", "Low"), ("medium", "Medium"), ("high", "High"), ("critical", "Critical")],
        required=True,
        default="medium",
        tracking=True,
        index=True,
    )
    state = fields.Selection(
        [
            ("new", "New"),
            ("open", "Open"),
            ("pending_customer", "Pending Customer"),
            ("pending_internal", "Pending Internal"),
            ("escalated", "Escalated"),
            ("resolved", "Resolved"),
            ("closed", "Closed"),
            ("reopened", "Reopened"),
        ],
        required=True,
        default="new",
        tracking=True,
        copy=False,
        index=True,
    )
    assigned_user_id = fields.Many2one(
        "res.users", ondelete="restrict", tracking=True, index=True
    )
    supervisor_membership_id = fields.Many2one(
        "cc.campaign.membership", ondelete="restrict", readonly=True, index=True
    )
    sla_policy_id = fields.Many2one(
        "cc.helpdesk.sla.policy", required=True, ondelete="restrict", readonly=True
    )
    opened_at = fields.Datetime(
        required=True, default=fields.Datetime.now, readonly=True, copy=False, index=True
    )
    first_response_due_at = fields.Datetime(required=True, readonly=True, index=True)
    resolution_due_at = fields.Datetime(required=True, readonly=True, index=True)
    first_response_at = fields.Datetime(readonly=True, copy=False, index=True)
    resolved_at = fields.Datetime(readonly=True, copy=False, index=True)
    closed_at = fields.Datetime(readonly=True, copy=False, index=True)
    sla_state = fields.Selection(
        [("on_track", "On Track"), ("response_breached", "First Response Breached"), ("resolution_breached", "Resolution Breached"), ("met", "Met")],
        required=True,
        default="on_track",
        readonly=True,
        index=True,
    )
    escalation_reason = fields.Char(tracking=True)
    resolution = fields.Text(tracking=True)
    resolution_code = fields.Char(index=True)
    first_contact_resolution = fields.Boolean(default=False, tracking=True)
    csat_score = fields.Integer()

    _ticket_uuid_unique = models.Constraint(
        "unique(ticket_uuid)", "Helpdesk ticket UUIDs must be unique."
    )
    _ticket_number_unique = models.Constraint(
        "unique(ticket_number)", "Helpdesk ticket numbers must be unique."
    )
    _integration_key_unique = models.Constraint(
        "unique(campaign_id, integration_key)",
        "Ticket integration keys must be unique inside a campaign.",
    )
    _csat_range = models.Constraint(
        "check(csat_score IS NULL OR (csat_score >= 1 AND csat_score <= 5))",
        "CSAT must be between one and five.",
    )

    @api.model_create_multi
    def create(self, values_list):
        prepared = []
        for original in values_list:
            values = dict(original)
            server_managed = {
                "ticket_uuid",
                "ticket_number",
                "integration_key",
                "sla_policy_id",
                "first_response_due_at",
                "resolution_due_at",
                "supervisor_membership_id",
                "opened_at",
                "first_response_at",
                "resolved_at",
                "closed_at",
                "sla_state",
                "csat_score",
            }
            if (
                server_managed.intersection(values)
                or values.get("state", "new") != "new"
            ) and self.env.context.get(
                "_cc_ticket_import_capability"
            ) is not TICKET_IMPORT_CAPABILITY:
                raise AccessError(_("Ticket workflow and SLA evidence are server-managed."))
            profile = self.env["cc.customer.profile"].browse(
                values.get("customer_profile_id")
            ).exists()
            queue = self.env["cc.helpdesk.queue"].browse(values.get("queue_id")).exists()
            if not profile or not queue:
                raise ValidationError(_("A campaign customer profile and queue are required."))
            profile.check_access("read")
            queue.check_access("read")
            campaign = _ticket_campaign(
                self.env, values.get("campaign_id"), profile=profile, queue=queue
            )
            values["campaign_id"] = campaign.id
            values["ticket_number"] = (
                self.env["ir.sequence"].next_by_code("cc.helpdesk.ticket") or "New"
            )
            values.setdefault("opened_at", fields.Datetime.now())
            policy = self.env["cc.helpdesk.sla.policy"].search(
                [
                    ("queue_id", "=", queue.id),
                    ("campaign_id", "=", campaign.id),
                    ("priority", "=", values.get("priority", "1")),
                    ("state", "=", "approved"),
                ],
                limit=1,
            )
            if not policy:
                raise ValidationError(_("An approved same-campaign SLA is required."))
            opened_at = fields.Datetime.to_datetime(values["opened_at"])
            values.update(
                {
                    "sla_policy_id": policy.id,
                    "first_response_due_at": opened_at + timedelta(minutes=policy.first_response_minutes),
                    "resolution_due_at": opened_at + timedelta(minutes=policy.resolution_minutes),
                    "supervisor_membership_id": campaign.primary_supervisor_membership_id.id,
                }
            )
            if _is_operational(self.env.user) and not values.get("assigned_user_id"):
                values["assigned_user_id"] = self.env.user.id
            prepared.append(values)
        records = super().create(prepared)
        records._validate_scope()
        return records

    @api.model
    def _create_imported(self, values):
        if not _is_global_admin(self.env.user):
            raise AccessError(_("Global contact-center migration permission is required."))
        return self.with_context(
            _cc_ticket_import_capability=TICKET_IMPORT_CAPABILITY
        ).create(values)

    def write(self, values):
        protected = {
            "campaign_id",
            "customer_profile_id",
            "queue_id",
            "sla_policy_id",
            "first_response_due_at",
            "resolution_due_at",
            "supervisor_membership_id",
            "opened_at",
            "priority",
            "ticket_uuid",
            "ticket_number",
            "integration_key",
            "first_response_at",
            "resolved_at",
            "closed_at",
            "sla_state",
        }
        if protected.intersection(values) and self.env.context.get(
            "_cc_ticket_workflow_capability"
        ) is not TICKET_WORKFLOW_CAPABILITY:
            raise AccessError(_("Ticket ownership and SLA evidence are server-managed."))
        if "state" in values and self.env.context.get(
            "_cc_ticket_workflow_capability"
        ) is not TICKET_WORKFLOW_CAPABILITY:
            raise AccessError(_("Ticket state changes require the governed workflow."))
        if _is_operational(self.env.user) and not _is_supervisor(self.env.user) and {
            "assigned_user_id",
        }.intersection(values):
            raise AccessError(_("Agents cannot reassign campaign tickets."))
        if _is_operational(self.env.user) and "csat_score" in values:
            raise AccessError(_("Operational users cannot write customer CSAT evidence."))
        result = super().write(values)
        self._validate_scope()
        return result

    def unlink(self):
        raise AccessError(_("Campaign helpdesk tickets are retained, not deleted."))

    def copy(self, default=None):
        raise AccessError(_("Campaign helpdesk tickets cannot be copied."))

    def export_data(self, fields_to_export, raw_data=False):
        if _is_operational(self.env.user):
            raise UserError(_("Agent and supervisor bulk export is disabled."))
        return super().export_data(fields_to_export, raw_data=raw_data)

    @api.constrains(
        "campaign_id",
        "queue_id",
        "customer_profile_id",
        "crm_lead_id",
        "mail_thread_id",
        "assigned_user_id",
        "sla_policy_id",
        "supervisor_membership_id",
        "description",
        "resolution",
    )
    def _validate_scope(self):
        for ticket in self:
            if ticket.queue_id.campaign_id != ticket.campaign_id:
                raise ValidationError(_("Ticket and queue campaigns differ."))
            if ticket.customer_profile_id.campaign_id != ticket.campaign_id:
                raise ValidationError(_("Ticket and customer profile campaigns differ."))
            if ticket.crm_lead_id and ticket.crm_lead_id.campaign_id != ticket.campaign_id:
                raise ValidationError(_("Ticket and CRM lead campaigns differ."))
            if ticket.mail_thread_id and ticket.mail_thread_id.campaign_id != ticket.campaign_id:
                raise ValidationError(_("Ticket and mail thread campaigns differ."))
            if ticket.sla_policy_id.campaign_id != ticket.campaign_id:
                raise ValidationError(_("Ticket and SLA policy campaigns differ."))
            supervisor = ticket.supervisor_membership_id
            if supervisor and (
                supervisor.campaign_id != ticket.campaign_id
                or supervisor.state != "active"
                or supervisor.role != "supervisor"
                or not supervisor.is_primary_supervisor
            ):
                raise ValidationError(_("Ticket escalation supervisor is not authoritative."))
            if ticket.assigned_user_id:
                membership = self.env["cc.campaign.membership"].search(
                    [
                        ("user_id", "=", ticket.assigned_user_id.id),
                        ("campaign_id", "=", ticket.campaign_id.id),
                        ("state", "=", "active"),
                        ("role", "in", ("agent", "senior_agent", "supervisor")),
                    ],
                    limit=1,
                )
                if not membership:
                    raise ValidationError(_("Ticket assignee is outside the campaign."))
            combined = " ".join((ticket.description or "", ticket.resolution or "")).lower()
            if any(pattern in combined for pattern in FORBIDDEN_TEXT_PATTERNS):
                raise ValidationError(_("Secrets and payment credentials are prohibited."))
            if len(json.dumps(ticket.resolution or "")) > 8192:
                raise ValidationError(_("Ticket resolution exceeds the safe limit."))

    def _transition(self, target, extra=None):
        allowed = {
            "new": {"open", "escalated"},
            "open": {"pending_customer", "pending_internal", "escalated", "resolved"},
            "pending_customer": {"open", "escalated", "resolved"},
            "pending_internal": {"open", "escalated", "resolved"},
            "escalated": {"open", "resolved"},
            "resolved": {"closed", "reopened"},
            "closed": {"reopened"},
            "reopened": {"open", "escalated", "resolved"},
        }
        for ticket in self:
            if target not in allowed.get(ticket.state, set()):
                raise ValidationError(
                    _(
                        "Ticket transition from %(source)s to %(target)s is not allowed.",
                        source=ticket.state,
                        target=target,
                    )
                )
            values = {"state": target, **(extra or {})}
            if target == "resolved":
                if not (values.get("resolution") or ticket.resolution):
                    raise ValidationError(_("A resolution is required."))
                values["resolved_at"] = fields.Datetime.now()
            if target == "closed":
                values["closed_at"] = fields.Datetime.now()
            if target == "reopened":
                values.update({"closed_at": False, "resolved_at": False})
            ticket.with_context(
                _cc_ticket_workflow_capability=TICKET_WORKFLOW_CAPABILITY
            ).write(values)
            ticket.action_refresh_sla_state()
        return True

    def action_start(self):
        return self._transition("open")

    def action_wait_customer(self):
        return self._transition("pending_customer")

    def action_wait_internal(self):
        return self._transition("pending_internal")

    def action_escalate(self):
        if any(not (ticket.escalation_reason or "").strip() for ticket in self):
            raise ValidationError(_("An escalation reason is required."))
        return self._transition("escalated")

    def action_record_first_response(self):
        now = fields.Datetime.now()
        for ticket in self:
            if ticket.state in {"resolved", "closed"}:
                raise ValidationError(
                    _("First-response evidence cannot be added after resolution.")
                )
            if ticket.first_response_at:
                raise ValidationError(_("First response evidence already exists."))
            ticket.with_context(
                _cc_ticket_workflow_capability=TICKET_WORKFLOW_CAPABILITY
            ).write({"first_response_at": now})
            ticket.action_refresh_sla_state()
        return True

    def action_resolve(self):
        return self._transition("resolved")

    def action_close(self):
        return self._transition("closed")

    def action_reopen(self):
        return self._transition("reopened")

    def action_refresh_sla_state(self):
        now = fields.Datetime.now()
        for ticket in self:
            if ticket.resolved_at:
                state = (
                    "met"
                    if ticket.resolved_at <= ticket.resolution_due_at
                    else "resolution_breached"
                )
            elif now > ticket.resolution_due_at:
                state = "resolution_breached"
            elif not ticket.first_response_at and now > ticket.first_response_due_at:
                state = "response_breached"
            else:
                state = "on_track"
            ticket.with_context(
                _cc_ticket_workflow_capability=TICKET_WORKFLOW_CAPABILITY
            ).write({"sla_state": state})
        return True
