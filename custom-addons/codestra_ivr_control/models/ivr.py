from odoo import api, fields, models
from odoo.exceptions import ValidationError


class IvrScopedMixin(models.AbstractModel):
    _name = "codestra.ivr.scoped.mixin"
    _description = "IVR Business Unit and Campaign Scope"

    business_unit_id = fields.Many2one("call.center.business.unit", required=True, index=True)
    campaign_id = fields.Many2one("call.center.campaign", index=True)
    test_only = fields.Boolean(default=True, required=True)
    active = fields.Boolean(default=False)

    @api.constrains("business_unit_id", "campaign_id")
    def _check_campaign_scope(self):
        for record in self:
            if record.campaign_id and record.campaign_id.business_unit_id != record.business_unit_id:
                raise ValidationError("IVR records cannot cross business-unit boundaries.")


class IvrSession(models.Model):
    _name = "codestra.ivr.session"
    _description = "IVR Session"
    _inherit = ["codestra.ivr.scoped.mixin"]

    reference = fields.Char(required=True, index=True)
    call_uniqueid = fields.Char(required=True, index=True)
    parent_call_reference = fields.Char()
    source_did = fields.Char(required=True)
    masked_caller_reference = fields.Char(required=True)
    initial_language = fields.Char(required=True, default="en")
    final_language = fields.Char(required=True, default="en")
    inbound_group = fields.Char()
    ivr_path = fields.Text()
    intent_code = fields.Char()
    customer_match_state = fields.Char(default="no_match")
    appointment_match_state = fields.Char(default="appointment_not_found")
    priority = fields.Integer(default=0)
    verification_state = fields.Char(default="unverified")
    invalid_input_count = fields.Integer(default=0)
    no_input_count = fields.Integer(default=0)
    queue_entry_at = fields.Datetime()
    agent_answer_at = fields.Datetime()
    abandon_at = fields.Datetime()
    final_result = fields.Char()
    correlation_id = fields.Char(required=True, index=True)
    campaign_lock = fields.Char(index=True)
    routing_signature_reference = fields.Char()
    archived_test_fixture = fields.Boolean(default=False)

    _reference_unique = models.Constraint("unique(reference)", "IVR session reference must be unique.")
    _call_unique = models.Constraint("unique(call_uniqueid)", "Call UniqueID must be idempotent.")


class IvrMenu(models.Model):
    _name = "codestra.ivr.menu"
    _description = "Versioned IVR Menu"
    _inherit = ["codestra.ivr.scoped.mixin"]

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    version = fields.Integer(required=True, default=1)
    language = fields.Char(default="en", required=True)
    state = fields.Selection([
        ("draft", "Draft"), ("testing", "Testing"), ("approved", "Approved"),
        ("published", "Published"), ("archived", "Archived"),
    ], default="draft", required=True)
    effective_at = fields.Datetime()
    expires_at = fields.Datetime()
    _version_unique = models.Constraint(
        "unique(code, version, language, business_unit_id)",
        "Menu versions must be unique within a business unit.",
    )


class IvrOption(models.Model):
    _name = "codestra.ivr.option"
    _description = "IVR Menu Option"
    _inherit = ["codestra.ivr.scoped.mixin"]

    menu_id = fields.Many2one("codestra.ivr.menu", required=True, ondelete="cascade")
    keypad_value = fields.Char(required=True)
    spoken_prompt = fields.Text(required=True)
    language = fields.Char(required=True, default="en")
    destination_type = fields.Selection([
        ("submenu", "Submenu"), ("queue", "Queue"), ("callback", "Callback"),
        ("lookup", "Lookup"), ("repeat", "Repeat"), ("fail_closed", "Fail Closed"),
    ], required=True)
    destination_campaign_id = fields.Many2one("call.center.campaign")
    destination_inbound_group = fields.Char()
    destination_submenu_id = fields.Many2one("codestra.ivr.menu")
    priority = fields.Integer(default=0)
    verification_required = fields.Boolean(default=False)
    approval_state = fields.Selection([
        ("draft", "Draft"), ("approved", "Approved"), ("published", "Published"),
    ], default="draft", required=True)

    @api.constrains("menu_id", "business_unit_id")
    def _check_menu_scope(self):
        for record in self:
            if record.menu_id.business_unit_id != record.business_unit_id:
                raise ValidationError("IVR option and menu must share a business unit.")


class DidMapping(models.Model):
    _name = "codestra.ivr.did.mapping"
    _description = "IVR DID Mapping"
    _inherit = ["codestra.ivr.scoped.mixin"]

    did_reference = fields.Char(required=True, index=True)
    environment = fields.Selection([
        ("development", "Development"), ("test", "Test"), ("staging", "Staging"),
        ("production", "Production"),
    ], default="staging", required=True)
    default_campaign_id = fields.Many2one("call.center.campaign")
    root_menu_id = fields.Many2one("codestra.ivr.menu", required=True)
    language = fields.Char(default="en", required=True)
    schedule_id = fields.Many2one("codestra.ivr.schedule")
    after_hours_menu_id = fields.Many2one("codestra.ivr.menu")
    holiday_menu_id = fields.Many2one("codestra.ivr.menu")
    production_eligible = fields.Boolean(default=False)
    _did_unique = models.Constraint(
        "unique(did_reference, environment)", "DID references must be deterministic per environment."
    )


class Destination(models.Model):
    _name = "codestra.ivr.destination"
    _description = "IVR Destination Registry"
    _inherit = ["codestra.ivr.scoped.mixin"]

    code = fields.Char(required=True, index=True)
    native_campaign_id = fields.Char(required=True, index=True)
    inbound_group = fields.Char(required=True)
    department_id = fields.Many2one("call.center.department", required=True)
    queue = fields.Char(required=True)
    supervisor_group = fields.Char(required=True)
    language_requirements = fields.Char(default="en")
    permitted_transfers = fields.Char()
    callback_policy = fields.Char(required=True)
    external_destination = fields.Boolean(default=False)
    _native_unique = models.Constraint(
        "unique(native_campaign_id)", "Native VICIdial campaign IDs must be unique."
    )


def _simple_scoped_model(model_name, description):
    return type(model_name.replace(".", "_"), (models.Model,), {
        "__module__": __name__,
        "_name": model_name,
        "_description": description,
        "_inherit": ["codestra.ivr.scoped.mixin"],
        "name": fields.Char(required=True),
        "safe_state": fields.Char(default="disabled", required=True),
        "correlation_id": fields.Char(index=True),
    })


QueuePolicy = _simple_scoped_model("codestra.ivr.queue.policy", "IVR Queue Policy")
Schedule = _simple_scoped_model("codestra.ivr.schedule", "IVR Schedule")
Holiday = _simple_scoped_model("codestra.ivr.holiday", "IVR Holiday")
Language = _simple_scoped_model("codestra.ivr.language", "IVR Language")
CustomerLookup = _simple_scoped_model("codestra.ivr.customer.lookup", "IVR Customer Lookup")
AppointmentLookup = _simple_scoped_model("codestra.ivr.appointment.lookup", "IVR Appointment Lookup")
CallbackRequest = _simple_scoped_model("codestra.ivr.callback.request", "IVR Callback Request")
Reclassification = _simple_scoped_model("codestra.ivr.reclassification", "IVR Reclassification")
AuditEvent = _simple_scoped_model("codestra.ivr.audit.event", "IVR Audit Event")
MetricSnapshot = _simple_scoped_model("codestra.ivr.metric.snapshot", "IVR Metric Snapshot")
