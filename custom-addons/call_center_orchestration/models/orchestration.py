import hashlib
import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError


SAFE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,254}$")


class CallCenterTeam(models.Model):
    _inherit = "call.center.team"

    department_id = fields.Many2one(
        "call.center.department", required=True, ondelete="restrict", index=True
    )
    external_group_reference = fields.Char(copy=False)

    @api.constrains("department_id", "business_unit_id")
    def _check_department_unit(self):
        for team in self:
            if team.department_id.business_unit_id != team.business_unit_id:
                raise ValidationError("Team and department business units must match.")


class CallCenterCampaign(models.Model):
    _inherit = "call.center.campaign"

    vicidial_campaign_reference = fields.Char(copy=False)
    inbound_group_reference = fields.Char(copy=False)
    default_list_reference = fields.Char(copy=False)


class ResUsers(models.Model):
    _inherit = "res.users"

    call_center_team_ids = fields.Many2many(
        "call.center.team", "call_center_orchestration_user_team_rel", string="Teams"
    )
    identity_lifecycle_state = fields.Selection(
        [
            ("unmanaged", "Unmanaged"),
            ("requested", "Provisioning Requested"),
            ("active", "Active"),
            ("suspended", "Suspended"),
            ("revoked", "Revoked"),
        ],
        default="unmanaged",
        required=True,
        copy=False,
    )


class ProvisioningRequest(models.Model):
    _name = "call.center.provisioning.request"
    _description = "Synthetic-Safe Identity Provisioning Request"
    _inherit = ["mail.thread", "call.center.business.unit.mixin"]
    _order = "create_date desc"

    request_uid = fields.Char(required=True, index=True, copy=False)
    operation = fields.Selection(
        [("provision", "Provision"), ("offboard", "Offboard")],
        required=True,
        default="provision",
    )
    user_id = fields.Many2one("res.users", required=True, ondelete="restrict")
    department_id = fields.Many2one(
        "call.center.department", required=True, ondelete="restrict"
    )
    team_id = fields.Many2one("call.center.team", required=True, ondelete="restrict")
    supervisor_id = fields.Many2one("res.users", required=True, ondelete="restrict")
    campaign_ids = fields.Many2many("call.center.campaign")
    requested_roles = fields.Char(required=True)
    keycloak_subject_reference = fields.Char(copy=False)
    vicidial_user_reference = fields.Char(copy=False)
    endpoint_reference = fields.Char(copy=False)
    credential_reference_ids = fields.One2many(
        "call.center.credential.reference", "provisioning_request_id"
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("approved", "Approved"),
            ("queued", "Queued"),
            ("completed", "Completed"),
            ("failed", "Failed"),
            ("revoked", "Revoked"),
        ],
        default="draft",
        required=True,
        tracking=True,
        copy=False,
    )
    correlation_id = fields.Char(required=True, index=True, copy=False)
    idempotency_key_hash = fields.Char(required=True, index=True, copy=False)
    expires_at = fields.Datetime(required=True)
    completed_at = fields.Datetime(copy=False)
    safe_failure_code = fields.Char(copy=False)

    _request_uid_unique = models.Constraint(
        "unique(request_uid)", "Provisioning request identifiers must be unique."
    )
    _idempotency_unique = models.Constraint(
        "unique(idempotency_key_hash)",
        "Provisioning idempotency hashes must be unique.",
    )

    @api.constrains(
        "business_unit_id", "user_id", "department_id", "team_id",
        "supervisor_id", "campaign_ids"
    )
    def _check_hierarchy(self):
        for request in self:
            unit = request.business_unit_id
            if request.department_id.business_unit_id != unit:
                raise ValidationError("Department is outside the request business unit.")
            if request.team_id.business_unit_id != unit:
                raise ValidationError("Team is outside the request business unit.")
            if request.team_id.department_id != request.department_id:
                raise ValidationError("Team is outside the selected department.")
            if request.user_id not in request.team_id.agent_ids:
                raise ValidationError("Agent must be assigned to the selected team.")
            if request.supervisor_id not in request.team_id.supervisor_ids:
                raise ValidationError("Supervisor must be assigned to the selected team.")
            if any(campaign.business_unit_id != unit for campaign in request.campaign_ids):
                raise ValidationError("Campaign permissions cannot cross business units.")

    def action_queue(self):
        for request in self:
            if request.state != "approved":
                raise ValidationError("Only approved requests may be queued.")
            if request.expires_at <= fields.Datetime.now():
                raise ValidationError("The provisioning authorization has expired.")
            request.state = "queued"
            request.user_id.identity_lifecycle_state = "requested"
        return True

    def action_revoke(self):
        self.write({"state": "revoked", "completed_at": fields.Datetime.now()})
        self.mapped("user_id").write({"identity_lifecycle_state": "revoked"})
        self.mapped("credential_reference_ids").write(
            {"status": "revoked", "revoked_at": fields.Datetime.now()}
        )
        return True


class CredentialReference(models.Model):
    _name = "call.center.credential.reference"
    _description = "Protected Credential Reference"
    _inherit = "call.center.business.unit.mixin"
    _order = "create_date desc"

    provisioning_request_id = fields.Many2one(
        "call.center.provisioning.request", required=True, ondelete="cascade"
    )
    credential_type = fields.Selection(
        [
            ("odoo_activation", "Odoo Activation"),
            ("keycloak_activation", "Keycloak Activation"),
            ("vicidial", "VICIdial"),
            ("sip", "SIP / WebRTC"),
        ],
        required=True,
    )
    vault_reference = fields.Char(required=True, copy=False)
    fingerprint = fields.Char(required=True, copy=False)
    retrieval_token_hash = fields.Char(required=True, copy=False)
    status = fields.Selection(
        [
            ("pending", "Pending"),
            ("available", "Available"),
            ("retrieved", "Retrieved"),
            ("expired", "Expired"),
            ("revoked", "Revoked"),
        ],
        default="pending",
        required=True,
        copy=False,
    )
    expires_at = fields.Datetime(required=True)
    retrieved_at = fields.Datetime(copy=False)
    revoked_at = fields.Datetime(copy=False)

    _token_hash_unique = models.Constraint(
        "unique(retrieval_token_hash)", "Retrieval-token hashes must be unique."
    )

    @api.constrains("vault_reference", "fingerprint", "retrieval_token_hash")
    def _check_safe_metadata(self):
        for record in self:
            if not SAFE_REFERENCE.fullmatch(record.vault_reference or ""):
                raise ValidationError("Credential references must use a protected reference.")
            if len(record.fingerprint or "") < 16:
                raise ValidationError("Credential fingerprint is invalid.")
            if len(record.retrieval_token_hash or "") != 64:
                raise ValidationError("Only a SHA-256 retrieval-token hash may be stored.")

    @api.model
    def token_fingerprint(self, token):
        return hashlib.sha256(token.encode()).hexdigest()


class CallbackTask(models.Model):
    _name = "call.center.callback.task"
    _description = "Callback Reminder and Escalation"
    _inherit = ["mail.thread", "mail.activity.mixin", "call.center.business.unit.mixin"]
    _order = "due_at, id"

    lead_id = fields.Many2one("crm.lead", required=True, ondelete="cascade")
    campaign_id = fields.Many2one("call.center.campaign", required=True)
    agent_id = fields.Many2one("res.users", required=True)
    supervisor_id = fields.Many2one("res.users", required=True)
    due_at = fields.Datetime(required=True, index=True)
    reminder_at = fields.Datetime(index=True)
    escalated_at = fields.Datetime(copy=False)
    completed_at = fields.Datetime(copy=False)
    state = fields.Selection(
        [
            ("scheduled", "Scheduled"),
            ("reminded", "Reminded"),
            ("overdue", "Overdue"),
            ("escalated", "Escalated"),
            ("completed", "Completed"),
            ("canceled", "Canceled"),
        ],
        default="scheduled",
        required=True,
        tracking=True,
    )
    correlation_id = fields.Char(required=True, index=True)

    @api.constrains("business_unit_id", "lead_id", "campaign_id")
    def _check_unit(self):
        for task in self:
            if task.lead_id.business_unit_id != task.business_unit_id:
                raise ValidationError("Callback lead is outside the business unit.")
            if task.campaign_id.business_unit_id != task.business_unit_id:
                raise ValidationError("Callback campaign is outside the business unit.")

    @api.model
    def _cron_callback_reminders(self):
        now = fields.Datetime.now()
        due = self.search([
            ("state", "=", "scheduled"), ("reminder_at", "!=", False),
            ("reminder_at", "<=", now),
        ])
        due.write({"state": "reminded"})
        overdue = self.search([
            ("state", "in", ["scheduled", "reminded"]), ("due_at", "<", now),
        ])
        overdue.write({"state": "escalated", "escalated_at": now})


class CallbackNotification(models.Model):
    _name = "call.center.callback.notification"
    _description = "Idempotent Callback Notification Intent"
    _inherit = "call.center.business.unit.mixin"

    callback_id = fields.Many2one(
        "call.center.callback.task", required=True, ondelete="cascade", index=True
    )
    notification_type = fields.Selection(
        [
            ("before_24h", "24 Hours Before"),
            ("before_1h", "1 Hour Before"),
            ("before_15m", "15 Minutes Before"),
            ("scheduled", "At Scheduled Time"),
            ("overdue_15m", "15 Minutes Overdue"),
            ("overdue_1h", "1 Hour Overdue"),
            ("daily_summary", "Daily Unresolved Summary"),
        ],
        required=True,
    )
    scheduled_window = fields.Datetime(required=True, index=True)
    idempotency_key = fields.Char(required=True, index=True)
    recipient_role = fields.Selection(
        [("agent", "Agent"), ("supervisor", "Supervisor")], required=True
    )
    state = fields.Selection(
        [
            ("disabled", "Disabled"),
            ("pending", "Pending"),
            ("sent", "Sent"),
            ("canceled", "Canceled"),
        ],
        default="disabled",
        required=True,
    )

    _notification_unique = models.Constraint(
        "unique(callback_id, notification_type, scheduled_window)",
        "Callback notifications are idempotent by callback, type, and window.",
    )

    @api.constrains("callback_id", "business_unit_id")
    def _check_callback_unit(self):
        for notice in self:
            if notice.callback_id.business_unit_id != notice.business_unit_id:
                raise ValidationError("Callback notification is outside the business unit.")


class LeadImportBatch(models.Model):
    _name = "call.center.lead.import.batch"
    _description = "Idempotent Lead Import Batch"
    _inherit = ["mail.thread", "call.center.business.unit.mixin"]

    name = fields.Char(required=True)
    source_type = fields.Selection(
        [
            ("csv", "CSV"),
            ("xlsx", "Excel"),
            ("api", "API"),
            ("website", "Website"),
            ("partner", "Partner"),
        ],
        required=True,
    )
    source_reference = fields.Char(required=True)
    source_digest = fields.Char(required=True, size=64, index=True)
    campaign_id = fields.Many2one("call.center.campaign", required=True)
    vicidial_list_reference = fields.Char(required=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("validated", "Validated"),
            ("ready", "Ready"),
            ("completed", "Completed"),
            ("failed", "Failed"),
        ],
        default="draft",
        required=True,
    )
    row_count = fields.Integer(default=0)
    accepted_count = fields.Integer(default=0)
    duplicate_count = fields.Integer(default=0)
    blocked_count = fields.Integer(default=0)
    correlation_id = fields.Char(required=True, index=True)

    _source_digest_unique = models.Constraint(
        "unique(source_digest, business_unit_id)",
        "An import source may be accepted once per business unit.",
    )

    @api.constrains("campaign_id", "business_unit_id")
    def _check_campaign_unit(self):
        for batch in self:
            if batch.campaign_id.business_unit_id != batch.business_unit_id:
                raise ValidationError("Import campaign is outside the business unit.")


class LeadImportRow(models.Model):
    _name = "call.center.lead.import.row"
    _description = "Minimized Lead Import Staging Row"
    _inherit = "call.center.business.unit.mixin"

    batch_id = fields.Many2one(
        "call.center.lead.import.batch", required=True, ondelete="cascade", index=True
    )
    row_number = fields.Integer(required=True)
    external_reference = fields.Char(index=True)
    record_hash = fields.Char(required=True, size=64, index=True)
    normalized_phone_hash = fields.Char(size=64, index=True)
    normalized_email_hash = fields.Char(size=64, index=True)
    timezone = fields.Char()
    country_code = fields.Char(size=2)
    state = fields.Selection(
        [
            ("uploaded", "Uploaded"),
            ("validation_pending", "Validation Pending"),
            ("invalid", "Invalid"),
            ("duplicate_review", "Duplicate Review"),
            ("dnc_blocked", "DNC Blocked"),
            ("consent_blocked", "Consent Blocked"),
            ("validated", "Validated"),
            ("ready_for_sync", "Ready for Sync"),
            ("archived", "Archived"),
        ],
        default="uploaded",
        required=True,
    )

    _row_unique = models.Constraint(
        "unique(batch_id, row_number)", "Import row numbers must be unique per batch."
    )
    _record_hash_unique = models.Constraint(
        "unique(batch_id, record_hash)", "Duplicate rows cannot be staged twice."
    )


class LeadValidationResult(models.Model):
    _name = "call.center.lead.validation.result"
    _description = "Lead Validation Result"
    _inherit = "call.center.business.unit.mixin"

    row_id = fields.Many2one(
        "call.center.lead.import.row", required=True, ondelete="cascade", index=True
    )
    validation_code = fields.Selection(
        [
            ("valid", "Valid"),
            ("invalid_schema", "Invalid Schema"),
            ("invalid_phone", "Invalid Phone"),
            ("invalid_email", "Invalid Email"),
            ("duplicate", "Duplicate"),
            ("global_dnc", "Global DNC"),
            ("campaign_dnc", "Campaign DNC"),
            ("consent_missing", "Consent Missing"),
            ("unit_mismatch", "Business Unit Mismatch"),
        ],
        required=True,
    )
    safe_detail = fields.Char()
    checked_at = fields.Datetime(default=fields.Datetime.now, required=True)


class LeadMapping(models.Model):
    _name = "call.center.lead.mapping"
    _description = "Odoo to VICIdial Lead Mapping"
    _inherit = "call.center.business.unit.mixin"

    lead_id = fields.Many2one("crm.lead", required=True, ondelete="cascade", index=True)
    campaign_id = fields.Many2one("call.center.campaign", required=True)
    list_reference = fields.Char(required=True)
    vicidial_lead_reference = fields.Char(required=True, index=True)
    source_fingerprint = fields.Char(required=True, size=64)
    sync_state = fields.Selection(
        [
            ("sync_pending", "Sync Pending"),
            ("synced", "Synced"),
            ("sync_failed", "Sync Failed"),
            ("archived", "Archived"),
        ],
        default="sync_pending",
        required=True,
    )
    last_readback_at = fields.Datetime()

    _mapping_unique = models.Constraint(
        "unique(lead_id, campaign_id)", "A lead has one mapping per campaign."
    )

    @api.constrains("lead_id", "campaign_id", "business_unit_id")
    def _check_mapping_unit(self):
        for mapping in self:
            if (
                mapping.lead_id.business_unit_id != mapping.business_unit_id
                or mapping.campaign_id.business_unit_id != mapping.business_unit_id
            ):
                raise ValidationError("Lead mapping cannot cross business units.")


class CrmLead(models.Model):
    _inherit = "crm.lead"

    import_batch_id = fields.Many2one("call.center.lead.import.batch", index=True)
    vicidial_list_reference = fields.Char(copy=False, index=True)
    sync_state = fields.Selection(
        [
            ("not_eligible", "Not Eligible"),
            ("approved", "Approved"),
            ("queued_disabled", "Queued (Delivery Disabled)"),
            ("synchronized", "Synchronized"),
            ("failed", "Failed"),
            ("revoked", "Revoked"),
        ],
        default="not_eligible",
        required=True,
        copy=False,
    )
    sync_idempotency_hash = fields.Char(copy=False, index=True)

    def action_approve_vicidial_sync(self):
        for lead in self:
            lead.action_validate_lead()
            lead.assert_contact_allowed()
            if lead.validation_state != "valid":
                raise ValidationError("Only valid leads may be approved for synchronization.")
            if not lead.call_center_campaign_id.default_list_reference:
                raise ValidationError("Campaign has no approved VICIdial list reference.")
            lead.write({
                "vicidial_list_reference":
                    lead.call_center_campaign_id.default_list_reference,
                "sync_state": "queued_disabled",
                "sync_idempotency_hash": hashlib.sha256(
                    f"{lead.business_unit_id.code}:{lead.id}:lead-sync-v1".encode()
                ).hexdigest(),
            })
        return True
