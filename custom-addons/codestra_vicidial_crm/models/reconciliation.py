"""Authoritative Odoo-side CRM/VICIdial reconciliation records."""

from odoo import api, fields, models
from odoo.exceptions import ValidationError


VALID_MODELS = [("res.partner", "Contact"), ("crm.lead", "CRM Lead")]


class VicidialPhoneEndpoint(models.Model):
    _name = "vicidial.phone.endpoint"
    _description = "Normalised Phone Endpoint"
    _order = "write_date desc"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    partner_id = fields.Many2one("res.partner", index=True, ondelete="cascade")
    crm_lead_id = fields.Many2one("crm.lead", index=True, ondelete="cascade")
    raw_number = fields.Char(required=True)
    normalised_number = fields.Char(required=True, index=True)
    country_code = fields.Char()
    extension = fields.Char()
    number_type = fields.Selection(
        [("mobile", "Mobile"), ("landline", "Landline"), ("other", "Other")], default="other"
    )
    validation_state = fields.Selection(
        [("valid", "Valid"), ("invalid", "Invalid"), ("unverified", "Unverified")], default="unverified", required=True
    )
    callable_state = fields.Selection(
        [("callable", "Callable"), ("blocked", "Blocked"), ("unknown", "Unknown")], default="unknown", required=True
    )
    consent_state = fields.Selection(
        [("granted", "Granted"), ("denied", "Denied"), ("revoked", "Revoked"), ("unknown", "Unknown")],
        default="unknown",
        required=True,
    )
    suppression_state = fields.Selection(
        [("clear", "Clear"), ("active", "Suppressed"), ("unavailable", "Unavailable")],
        default="unavailable",
        required=True,
    )
    last_verified_at = fields.Datetime()
    active = fields.Boolean(default=True, index=True)

    @api.constrains("partner_id", "crm_lead_id")
    def _check_owner(self):
        for record in self:
            if bool(record.partner_id) == bool(record.crm_lead_id):
                raise ValidationError("A phone endpoint must belong to exactly one contact or CRM lead.")

    @api.constrains("normalised_number")
    def _check_e164(self):
        for record in self:
            value = record.normalised_number or ""
            if not value.startswith("+") or not value[1:].isdigit() or not 8 <= len(value[1:]) <= 15:
                raise ValidationError("Normalised phone must be a valid E.164 candidate.")


class VicidialEmailEndpoint(models.Model):
    _name = "vicidial.email.endpoint"
    _description = "Normalised Email Endpoint"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    partner_id = fields.Many2one("res.partner", index=True, ondelete="cascade")
    crm_lead_id = fields.Many2one("crm.lead", index=True, ondelete="cascade")
    raw_email = fields.Char(required=True)
    normalised_email = fields.Char(required=True, index=True)
    validation_state = fields.Selection(
        [("valid", "Valid"), ("invalid", "Invalid"), ("unverified", "Unverified")], default="unverified", required=True
    )
    active = fields.Boolean(default=True, index=True)
    last_verified_at = fields.Datetime()

    @api.constrains("partner_id", "crm_lead_id")
    def _check_owner(self):
        for record in self:
            if bool(record.partner_id) == bool(record.crm_lead_id):
                raise ValidationError("An email endpoint must belong to exactly one contact or CRM lead.")

    @api.constrains("normalised_email")
    def _check_email(self):
        for record in self:
            value = record.normalised_email or ""
            if value != value.strip().lower() or value.count("@") != 1:
                raise ValidationError("Normalised email must be trimmed, lowercase, and syntactically valid.")


class VicidialIdentityMap(models.Model):
    _name = "vicidial.identity.map"
    _description = "Odoo to VICIdial Identity Map"
    _order = "last_verified_at desc, id desc"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    environment_id = fields.Char(required=True, index=True)
    connector_id = fields.Char(required=True, index=True)
    odoo_model = fields.Selection(VALID_MODELS, required=True, index=True)
    odoo_record_id = fields.Integer(required=True, index=True)
    external_system = fields.Selection([("vicidial", "VICIdial")], required=True, default="vicidial")
    external_entity_type = fields.Selection([("lead", "Lead"), ("list_membership", "List Membership")], required=True)
    external_id = fields.Char(required=True, index=True)
    external_parent_id = fields.Char(index=True)
    payload_checksum = fields.Char(size=64)
    source_revision = fields.Char()
    active = fields.Boolean(default=True, index=True)
    last_synced_at = fields.Datetime()
    last_verified_at = fields.Datetime()

    @api.constrains("external_entity_type", "external_parent_id")
    def _check_membership_parent(self):
        for record in self:
            if record.external_entity_type == "list_membership" and not record.external_parent_id:
                raise ValidationError("List membership mappings require a campaign or list parent ID.")

    def _auto_init(self):
        result = super()._auto_init()
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS vicidial_identity_map_odoo_lead_active_uniq
            ON vicidial_identity_map
              (connector_id, environment_id, odoo_model, odoo_record_id, external_entity_type)
            WHERE active AND external_entity_type = 'lead'
        """)
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS vicidial_identity_map_odoo_membership_active_uniq
            ON vicidial_identity_map
              (connector_id, environment_id, odoo_model, odoo_record_id,
               external_entity_type, external_parent_id)
            WHERE active AND external_entity_type = 'list_membership'
        """)
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS vicidial_identity_map_external_active_uniq
            ON vicidial_identity_map
              (connector_id, environment_id, external_entity_type, external_id)
            WHERE active
        """)
        return result


class VicidialSyncRun(models.Model):
    _name = "vicidial.sync.run"
    _description = "CRM VICIdial Synchronisation Run"
    _order = "started_at desc"

    name = fields.Char(default="New", readonly=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    connector_id = fields.Char(required=True, index=True)
    started_at = fields.Datetime(required=True, default=fields.Datetime.now)
    completed_at = fields.Datetime()
    status = fields.Selection(
        [
            ("running", "Running"),
            ("succeeded", "Succeeded"),
            ("failed", "Failed"),
            ("skipped", "Skipped"),
            ("partial", "Partial"),
        ],
        required=True,
        default="running",
        index=True,
    )
    source_cursor = fields.Datetime()
    next_cursor = fields.Datetime()
    skip_reason = fields.Selection([("previous_run_active", "Previous Run Active")])
    processed_count = fields.Integer()
    created_count = fields.Integer()
    updated_count = fields.Integer()
    deactivated_count = fields.Integer()
    suppressed_count = fields.Integer()
    duplicate_count = fields.Integer()
    conflict_count = fields.Integer()
    failed_count = fields.Integer()
    cursor_lag_seconds = fields.Integer()
    correlation_id = fields.Char(index=True)
    error_summary = fields.Text()

    @api.model_create_multi
    def create(self, values_list):
        records = super().create(values_list)
        for record in records:
            if record.name == "New":
                record.name = f"SYNC-{record.id}"
        return records

    def _auto_init(self):
        result = super()._auto_init()
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS vicidial_sync_run_active_uniq
            ON vicidial_sync_run (company_id, connector_id)
            WHERE status = 'running'
        """)
        return result


class VicidialReconciliationIssue(models.Model):
    _name = "vicidial.reconciliation.issue"
    _description = "VICIdial Reconciliation Review"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    connector_id = fields.Char(required=True, index=True)
    issue_type = fields.Selection(
        [
            ("exact_duplicate", "Exact Duplicate"),
            ("phone_conflict", "Phone Conflict"),
            ("email_conflict", "Email Conflict"),
            ("identity_conflict", "Identity Conflict"),
            ("orphaned", "Orphaned"),
            ("legacy_unmapped", "Legacy Unmapped"),
            ("possible_match", "Possible Match"),
            ("invalid_reference", "Invalid Reference"),
        ],
        required=True,
        index=True,
    )
    status = fields.Selection(
        [
            ("open", "Open"),
            ("confirmed", "Confirmed Mapping"),
            ("rejected", "Rejected"),
            ("resolved", "Resolved"),
            ("left_separate", "Left Separate"),
        ],
        default="open",
        required=True,
        tracking=True,
    )
    odoo_model = fields.Selection(VALID_MODELS)
    odoo_record_id = fields.Integer()
    external_id = fields.Char(index=True)
    campaign_or_list_id = fields.Char()
    phone_match = fields.Char()
    email_match = fields.Char()
    confidence = fields.Float()
    recommended_action = fields.Char()
    canonical_odoo_record_id = fields.Integer()
    canonical_external_id = fields.Char()
    evidence_json = fields.Text(required=True, default="{}")
    resolution_note = fields.Text()
    resolved_at = fields.Datetime(readonly=True)
    resolved_by = fields.Many2one("res.users", readonly=True)

    def write(self, values):
        if "status" in values and values["status"] != "open":
            values.update(resolved_at=fields.Datetime.now(), resolved_by=self.env.user.id)
        result = super().write(values)
        if "status" in values:
            self.env["codestra.integration.audit"].create(
                {
                    "action": "vicidial_reconciliation_resolution",
                    "model_name": self._name,
                    "record_res_id": self.id,
                    "after_json": self.evidence_json,
                    "success": True,
                }
            )
        return result
