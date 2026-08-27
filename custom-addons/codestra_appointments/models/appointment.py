import uuid
from odoo import api, fields, models
from odoo.exceptions import ValidationError

STATES = [("draft","Draft"),("scheduled","Scheduled"),("confirmed","Confirmed"),
 ("reminder_pending","Reminder Pending"),("reminder_sent","Reminder Sent"),
 ("preparing","Preparing"),("due","Due"),("in_progress","In Progress"),
 ("completed","Completed"),("rescheduled","Rescheduled"),("cancelled","Cancelled"),
 ("customer_no_answer","Customer No Answer"),("agent_missed","Agent Missed"),
 ("customer_requested_callback","Customer Requested Callback"),
 ("supervisor_review","Supervisor Review"),("failed","Failed")]


class AppointmentType(models.Model):
    _name="codestra.appointment.type"; _description="Appointment Type"
    name=fields.Char(required=True); code=fields.Char(required=True)
    business_unit_id=fields.Many2one("call.center.business.unit", required=True)
    campaign_ids=fields.Many2many("call.center.campaign"); duration_minutes=fields.Integer(default=30)
    active=fields.Boolean(default=False)


class ReminderPolicy(models.Model):
    _name="codestra.appointment.reminder.policy"; _description="Appointment Reminder Policy"
    name=fields.Char(required=True); business_unit_id=fields.Many2one("call.center.business.unit", required=True)
    campaign_id=fields.Many2one("call.center.campaign"); popup_minutes=fields.Integer(default=15)
    warning_minutes=fields.Integer(default=5); pause_minutes=fields.Integer(default=2)
    supervisor_overdue_minutes=fields.Integer(default=5); manager_overdue_minutes=fields.Integer(default=15)
    active=fields.Boolean(default=False)


class Appointment(models.Model):
    _name="codestra.call.appointment"; _description="Call Appointment"
    _inherit=["mail.thread","call.center.business.unit.mixin"]
    reference=fields.Char(required=True, index=True); title=fields.Char(required=True)
    campaign_id=fields.Many2one("call.center.campaign", required=True)
    department_id=fields.Many2one("call.center.department", required=True)
    team_id=fields.Many2one("call.center.team", required=True)
    agent_id=fields.Many2one("res.users", required=True); supervisor_id=fields.Many2one("res.users", required=True)
    customer_id=fields.Many2one("res.partner"); lead_id=fields.Many2one("crm.lead")
    language=fields.Char(default="en"); type_id=fields.Many2one("codestra.appointment.type", required=True)
    scheduled_start=fields.Datetime(required=True, index=True); scheduled_end=fields.Datetime(required=True)
    customer_timezone=fields.Char(required=True); agent_timezone=fields.Char(required=True)
    campaign_timezone=fields.Char(required=True); priority=fields.Selection([("low","Low"),("normal","Normal"),("high","High")],default="normal")
    state=fields.Selection(STATES, default="draft", required=True, tracking=True)
    call_reason=fields.Char(); preparation_notes=fields.Text(); reminder_policy_id=fields.Many2one("codestra.appointment.reminder.policy")
    correlation_id=fields.Char(required=True); source_system=fields.Char(default="staging")
    _reference_unique=models.Constraint("unique(reference)","Appointment references must be unique.")

    @api.constrains("business_unit_id","campaign_id","department_id","team_id")
    def _check_scope(self):
        for row in self:
            if any(x.business_unit_id != row.business_unit_id for x in (row.campaign_id,row.department_id,row.team_id)):
                raise ValidationError("Appointment hierarchy cannot cross business units.")


class ReminderEvent(models.Model):
    _name="codestra.appointment.reminder.event"; _description="Appointment Reminder Event"
    appointment_id=fields.Many2one("codestra.call.appointment",required=True,ondelete="cascade")
    event_type=fields.Char(required=True); scheduled_at=fields.Datetime(required=True)
    executed_at=fields.Datetime(); recipient_id=fields.Many2one("res.users",required=True)
    channel=fields.Selection([("in_app","In App"),("email","Email"),("telephony","Telephony")],required=True)
    state=fields.Selection([("disabled","Disabled"),("scheduled","Scheduled"),("delivered","Delivered"),("failed","Failed")],default="disabled")
    idempotency_key=fields.Char(required=True,index=True); correlation_id=fields.Char(required=True)
    _event_unique=models.Constraint("unique(idempotency_key)","Reminder events must be idempotent.")


def _simple_model(name, description):
    return type(name.replace(".","_"), (models.Model,), {
        "__module__": __name__,
        "_name": name, "_description": description,
        "appointment_id": fields.Many2one("codestra.call.appointment",required=True,ondelete="cascade"),
        "state": fields.Char(required=True), "safe_detail": fields.Char(),
        "correlation_id": fields.Char(required=True),
    })

PreparationChecklist=_simple_model("codestra.appointment.preparation.checklist","Preparation Checklist")
PreparationItem=_simple_model("codestra.appointment.preparation.item","Preparation Item")
Acknowledgment=_simple_model("codestra.appointment.acknowledgment","Appointment Acknowledgment")
Escalation=_simple_model("codestra.appointment.escalation","Appointment Escalation")
TelephonyAction=_simple_model("codestra.appointment.telephony.action","Telephony Action Audit")
AppointmentAudit=_simple_model("codestra.appointment.audit","Appointment Audit")
MetricSnapshot=_simple_model("codestra.appointment.metric.snapshot","Appointment Metric Snapshot")

CALLBACK_STATES=[(x,x.replace("_"," ").title()) for x in ("draft","scheduled","reminder_pending","ready","due","in_progress","completed","snoozed","rescheduled","missed","escalated","cancelled","failed","blocked_compliance")]
CALLBACK_TRANSITIONS={
 "draft":{"scheduled","cancelled","blocked_compliance"},"scheduled":{"reminder_pending","ready","due","snoozed","rescheduled","cancelled","blocked_compliance"},
 "reminder_pending":{"ready","due","snoozed","rescheduled","cancelled","failed"},"ready":{"due","snoozed","rescheduled","cancelled"},
 "due":{"in_progress","snoozed","rescheduled","missed","cancelled"},"in_progress":{"completed","failed","rescheduled"},
 "snoozed":{"reminder_pending","ready","due","rescheduled","cancelled"},"rescheduled":{"reminder_pending","ready","due","snoozed","cancelled"},
 "missed":{"escalated","in_progress","rescheduled","cancelled"},"escalated":{"in_progress","rescheduled","cancelled","failed"},
 "failed":{"scheduled","cancelled"},"blocked_compliance":{"scheduled","cancelled"},"completed":set(),"cancelled":set()}

class Callback(models.Model):
    _name="codestra.callback"; _description="Codestra Callback"; _inherit=["mail.thread","call.center.business.unit.mixin"]; _order="priority desc, scheduled_at"
    callback_uuid=fields.Char(required=True,default=lambda self:str(uuid.uuid4()),copy=False,index=True)
    campaign_id=fields.Many2one("call.center.campaign",required=True,index=True)
    contact_id=fields.Many2one("res.partner",index=True); lead_id=fields.Many2one("crm.lead",index=True); opportunity_id=fields.Many2one("crm.lead",index=True)
    original_call_id=fields.Char(index=True); original_linkedid=fields.Char(index=True)
    assigned_agent_id=fields.Many2one("res.users",index=True); assigned_team_id=fields.Many2one("call.center.team",index=True); supervisor_id=fields.Many2one("res.users")
    phone_number=fields.Char(required=True,groups="codestra.group_agent"); normalized_phone=fields.Char(required=True,index=True,groups="codestra.group_supervisor")
    scheduled_at=fields.Datetime(required=True,index=True,tracking=True); customer_timezone=fields.Char(required=True)
    priority=fields.Selection([("low","Low"),("normal","Normal"),("high","High"),("urgent","Urgent")],default="normal",required=True,index=True)
    reason=fields.Char(required=True,tracking=True); notes=fields.Text(); state=fields.Selection(CALLBACK_STATES,default="draft",required=True,index=True,tracking=True)
    reminder_email_enabled=fields.Boolean(default=True); reminder_popup_enabled=fields.Boolean(default=True)
    email_reminder_1_at=fields.Datetime(); email_reminder_2_at=fields.Datetime(); popup_reminder_at=fields.Datetime()
    attempt_count=fields.Integer(default=0); max_attempts=fields.Integer(default=3); last_attempt_at=fields.Datetime(); next_attempt_at=fields.Datetime(index=True)
    completed_at=fields.Datetime(); cancelled_at=fields.Datetime(); completion_disposition=fields.Char(); completion_notes=fields.Text()
    correlation_id=fields.Char(required=True,index=True,copy=False); idempotency_key=fields.Char(required=True,copy=False,index=True); version=fields.Integer(default=1,required=True)
    middleware_callback_uuid=fields.Char(copy=False,index=True,readonly=True)
    middleware_version=fields.Integer(default=0,readonly=True,copy=False)
    middleware_last_sync_at=fields.Datetime(readonly=True,copy=False)
    middleware_sync_state=fields.Selection([("pending","Pending"),("synced","Synced"),("reconciliation_required","Reconciliation Required")],default="pending",required=True)
    compliance_allowed=fields.Boolean(default=False); compliance_evidence=fields.Json(default=dict); history_ids=fields.One2many("codestra.callback.history","callback_id")
    _uuid_unique=models.Constraint("unique(callback_uuid)","Callback UUID must be unique.")
    _idem_unique=models.Constraint("unique(business_unit_id,idempotency_key)","Callback idempotency key must be unique per tenant.")
    _owner_required=models.Constraint("CHECK(assigned_agent_id IS NOT NULL OR assigned_team_id IS NOT NULL)","Callback requires an agent or team.")

    @api.constrains("business_unit_id","campaign_id","assigned_team_id")
    def _check_scope(self):
        for row in self:
            if row.campaign_id.business_unit_id!=row.business_unit_id or (row.assigned_team_id and row.assigned_team_id.business_unit_id!=row.business_unit_id):
                raise ValidationError("Callback cannot cross tenant or campaign scope.")

    def action_transition(self,target,correlation_id,actor_source="odoo"):
        for row in self:
            if target not in CALLBACK_TRANSITIONS.get(row.state,set()): raise ValidationError("Invalid callback transition: %s to %s"%(row.state,target))
            previous=row.state; values={"state":target,"version":row.version+1,"middleware_sync_state":"pending"}
            if target=="completed": values["completed_at"]=fields.Datetime.now()
            if target=="cancelled": values["cancelled_at"]=fields.Datetime.now()
            row.with_context(skip_callback_sync=True).write(values); self.env["codestra.callback.history"].create({"callback_id":row.id,"event_type":"callback.%s"%target,"from_state":previous,"to_state":target,"version":row.version,"actor_id":self.env.user.id,"actor_source":actor_source,"correlation_id":correlation_id})
            if not self.env.context.get("skip_callback_sync"):
                operation = "create" if not row.middleware_callback_uuid else target
                self.env["codestra.callback.sync.job"]._enqueue(row, operation, correlation_id)
        return True

    def action_schedule(self):
        return self.action_transition("scheduled", self.correlation_id)

    def action_start(self):
        return self.action_transition("in_progress", self.correlation_id)

    def action_complete(self):
        return self.action_transition("completed", self.correlation_id)

    def action_cancel(self):
        return self.action_transition("cancelled", self.correlation_id)

    def action_reconcile_middleware(self):
        for row in self:
            if row.middleware_callback_uuid:
                self.env["codestra.callback.sync.job"]._enqueue(
                    row, "reconcile", row.correlation_id
                )
        return True

class CallbackHistory(models.Model):
    _name="codestra.callback.history"; _description="Callback Audit History"; _order="occurred_at desc"; _log_access=False
    callback_id=fields.Many2one("codestra.callback",required=True,ondelete="restrict",index=True); event_type=fields.Char(required=True,index=True)
    from_state=fields.Char(); to_state=fields.Char(); version=fields.Integer(required=True); actor_id=fields.Many2one("res.users",required=True)
    actor_source=fields.Char(required=True); correlation_id=fields.Char(required=True,index=True); safe_detail=fields.Json(default=dict); occurred_at=fields.Datetime(default=fields.Datetime.now,required=True,index=True)
    def unlink(self): raise ValidationError("Callback audit history is append-only.")
