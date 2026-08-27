import copy
import uuid
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

ACTOR_TYPES=[("HUMAN","Human"),("AI","AI"),("SYSTEM","System")]
APPOINTMENT_STATES=[(x,x.replace("_"," ").title()) for x in (
 "SCHEDULED","CONFIRMED","REMINDER_SENT","RESCHEDULE_REQUESTED","RESCHEDULED",
 "CUSTOMER_ATTENDED","CUSTOMER_NO_SHOW","AGENT_NO_SHOW","COMPLETED","CANCELLED","FOLLOW_UP_REQUIRED")]
NOTE_VISIBILITIES=[(x,x.replace("_"," ").title()) for x in (
 "CUSTOMER_VISIBLE","INTERNAL","SUPERVISOR","QA","COMPLIANCE")]
AUTOMATION_ACTION_FIELDS={
    "CREATE_INTERNAL_SUMMARY":{"body"},
    "SET_NEXT_ACTION":{"next_action_type","next_action_at","next_action_owner_id"},
    "CHANGE_STATUS":{"status_code","required_values"},
}


class CodestraMailTemplate(models.Model):
    _inherit="mail.template"
    codestra_template_key=fields.Char(index=True,copy=False)
    codestra_template_version=fields.Integer(default=1,required=True)
    codestra_campaign_id=fields.Many2one("call.center.campaign",ondelete="restrict",index=True)
    codestra_locale=fields.Char(default="en_US",required=True)
    codestra_plain_body=fields.Text(required=False)
    codestra_sender_identity_ref=fields.Char(required=False)
    codestra_reply_to_identity_ref=fields.Char(required=False)
    codestra_safe_variables=fields.Json(default=list)
    codestra_approved=fields.Boolean(default=False,required=True,index=True)
    _codestra_template_key_unique=models.Constraint(
        "unique(codestra_template_key)","Codestra template keys must be unique."
    )


class CampaignWorkflow(models.Model):
    _name="codestra.campaign.workflow"; _description="Campaign Workflow"; _inherit=["mail.thread"]
    name=fields.Char(required=True,tracking=True); key=fields.Char(required=True,index=True)
    campaign_id=fields.Many2one("call.center.campaign",ondelete="restrict",index=True,tracking=True,
      help="Empty until an administrator explicitly approves the exact production campaign binding.")
    business_unit_id=fields.Many2one(related="campaign_id.business_unit_id",store=True,index=True)
    active=fields.Boolean(default=False,tracking=True); version=fields.Integer(default=1,required=True)
    lifecycle_state=fields.Selection([("DRAFT","Draft"),("VALIDATED","Validated"),("STAGING","Staging"),("ACTIVE","Active")],default="DRAFT",required=True,index=True,tracking=True)
    status_ids=fields.One2many("codestra.campaign.status","workflow_id")
    appointment_type_ids=fields.One2many("codestra.campaign.appointment.type","workflow_id")
    _key_unique=models.Constraint("unique(key)","Workflow keys must be unique.")
    _campaign_unique=models.Constraint("unique(campaign_id)","A campaign can have only one active workflow binding.")

    def action_validate_configuration(self):
        for row in self:
            if not row.campaign_id or len(row.status_ids) < 2: raise ValidationError("Campaign binding and at least two statuses are required.")
            if not row.status_ids.filtered("terminal"): raise ValidationError("A campaign workflow requires a terminal status.")
            if row.status_ids.filtered(lambda status:status.next_action_required and not status.default_next_action_type): raise ValidationError("Every next-action status requires a default action type.")
            row.write({"lifecycle_state":"VALIDATED","active":False})
        return True

    def action_stage(self):
        for row in self:
            if row.lifecycle_state!="VALIDATED": raise ValidationError("Validate the campaign workflow before staging.")
            row.write({"lifecycle_state":"STAGING","active":False})
        return True

    def action_activate(self):
        if not self.env.user.has_group("call_center_core.group_call_center_admin"): raise AccessError("Campaign activation requires administrator authority.")
        for row in self:
            if row.lifecycle_state!="STAGING": raise ValidationError("Only a staged workflow can be activated.")
            row.write({"lifecycle_state":"ACTIVE","active":True})
        return True


class CampaignStatus(models.Model):
    _name="codestra.campaign.status"; _description="Campaign-Specific Status"; _order="workflow_id,sequence,code"
    workflow_id=fields.Many2one("codestra.campaign.workflow",required=True,ondelete="cascade",index=True)
    campaign_id=fields.Many2one(related="workflow_id.campaign_id",store=True,index=True)
    code=fields.Char(required=True,index=True); display_name=fields.Char(required=True); sequence=fields.Integer(default=10)
    active=fields.Boolean(default=True); terminal=fields.Boolean(); won=fields.Boolean(); lost=fields.Boolean()
    requires_contact=fields.Boolean(); requires_note=fields.Boolean(); required_fields=fields.Json(default=list)
    allowed_previous_status_ids=fields.Many2many("codestra.campaign.status","codestra_status_previous_rel","status_id","previous_id")
    allowed_next_status_ids=fields.Many2many("codestra.campaign.status","codestra_status_next_rel","status_id","next_id")
    next_action_required=fields.Boolean(); default_next_action_type=fields.Char()
    followup_delay_minutes=fields.Integer(default=0); followup_sla_minutes=fields.Integer(default=0)
    allow_callback=fields.Boolean(); allow_appointment=fields.Boolean()
    appointment_type_ids=fields.Many2many("codestra.campaign.appointment.type")
    email_behavior=fields.Selection([
        ("NO_EMAIL","No Email"),("OPTIONAL_EMAIL","Optional Email"),
        ("AUTOMATIC_EMAIL","Automatic Email"),("AGENT_DRAFT","Agent Draft"),
        ("REQUIRES_APPROVAL","Requires Approval"),
    ],default="NO_EMAIL",required=True,index=True)
    email_template_id=fields.Many2one("mail.template",ondelete="set null"); sms_template_key=fields.Char()
    n8n_workflow_key=fields.Char(); supervisor_escalation_enabled=fields.Boolean()
    manager_escalation_enabled=fields.Boolean(); report_category=fields.Char(required=True)
    vicidial_disposition_codes=fields.Json(default=list); ai_allowed_actions=fields.Json(default=list)
    _code_workflow_unique=models.Constraint("unique(workflow_id,code)","Status codes must be unique per workflow.")

    @api.constrains("terminal","next_action_required","followup_sla_minutes","email_behavior","email_template_id")
    def _check_rule(self):
        for row in self:
            if row.terminal and row.next_action_required: raise ValidationError("Terminal status cannot require a next action.")
            if row.next_action_required and row.followup_sla_minutes <= 0: raise ValidationError("A required next action requires a positive SLA.")
            if row.email_behavior == "AUTOMATIC_EMAIL" and not row.email_template_id:
                raise ValidationError("Automatic email statuses require an approved campaign template.")


class CampaignFollowupRule(models.Model):
    _name="codestra.campaign.followup.rule"; _description="Campaign Follow-Up and SLA Rule"
    workflow_id=fields.Many2one("codestra.campaign.workflow",required=True,ondelete="cascade",index=True)
    status_id=fields.Many2one("codestra.campaign.status",required=True,ondelete="cascade",index=True)
    next_action_type=fields.Char(required=True); delay_minutes=fields.Integer(required=True)
    agent_reminder_minutes=fields.Integer(required=True); supervisor_escalation_minutes=fields.Integer(required=True)
    manager_escalation_minutes=fields.Integer(required=True); active=fields.Boolean(default=True)
    _status_unique=models.Constraint("unique(status_id)","A status has one authoritative follow-up rule.")
    @api.constrains("delay_minutes","agent_reminder_minutes","supervisor_escalation_minutes","manager_escalation_minutes")
    def _ordered_thresholds(self):
        for row in self:
            if not (0 <= row.agent_reminder_minutes <= row.supervisor_escalation_minutes <= row.manager_escalation_minutes):
                raise ValidationError("SLA thresholds must be ordered agent, supervisor, manager.")


class CampaignAppointmentType(models.Model):
    _name="codestra.campaign.appointment.type"; _description="Campaign Appointment Type"
    workflow_id=fields.Many2one("codestra.campaign.workflow",required=True,ondelete="cascade",index=True)
    campaign_id=fields.Many2one(related="workflow_id.campaign_id",store=True,index=True)
    code=fields.Char(required=True); name=fields.Char(required=True); duration_minutes=fields.Integer(default=30)
    active=fields.Boolean(default=True); confirmation_workflow_key=fields.Char(default="appointment_confirmation")
    _type_unique=models.Constraint("unique(workflow_id,code)","Appointment type codes must be unique per workflow.")


class CampaignDispositionMapping(models.Model):
    _name="codestra.campaign.disposition.mapping"; _description="Campaign-Aware VICIdial Disposition Mapping"
    workflow_id=fields.Many2one("codestra.campaign.workflow",required=True,ondelete="cascade",index=True)
    campaign_id=fields.Many2one(related="workflow_id.campaign_id",store=True,index=True)
    disposition_code=fields.Char(required=True,index=True); status_id=fields.Many2one("codestra.campaign.status",required=True,ondelete="restrict")
    active=fields.Boolean(default=True); requires_note=fields.Boolean(); create_callback=fields.Boolean()
    _mapping_unique=models.Constraint("unique(workflow_id,disposition_code)","Disposition mapping must include and be unique within a campaign workflow.")
    @api.constrains("workflow_id","status_id")
    def _scope(self):
        for row in self:
            if row.status_id.workflow_id != row.workflow_id: raise ValidationError("Disposition and status must share a workflow.")


class CampaignAutomation(models.Model):
    _name="codestra.campaign.automation"; _description="Campaign Automation Registry"
    workflow_id=fields.Many2one("codestra.campaign.workflow",required=True,ondelete="cascade",index=True)
    key=fields.Char(required=True,index=True); event_type=fields.Char(required=True); n8n_workflow_key=fields.Char(required=True)
    email_template_id=fields.Many2one("mail.template",ondelete="set null")
    activation_mode=fields.Selection([("DISABLED","Disabled"),("CANARY_ONLY","Canary Only"),("FULL","Full")],default="DISABLED",required=True,index=True)
    active=fields.Boolean(default=False); idempotency_required=fields.Boolean(default=True,readonly=True)
    allowed_action_types=fields.Json(default=list,help="Explicit Middleware/Odoo action allowlist for this campaign automation.")
    action_plan=fields.Json(default=list,help="Source-bound action templates. Entity targets are materialized only from the immutable outbox aggregate.")
    _automation_unique=models.Constraint("unique(workflow_id,key)","Automation keys must be unique per workflow.")

    @api.constrains("allowed_action_types","action_plan")
    def _check_action_plan(self):
        for row in self:
            allowed=row.allowed_action_types or []
            if not isinstance(allowed,list) or len(allowed)!=len(set(allowed)) or set(allowed)-set(AUTOMATION_ACTION_FIELDS):
                raise ValidationError("Automation action allowlist is invalid.")
            plan=row.action_plan or []
            if not isinstance(plan,list) or len(plan)>20:
                raise ValidationError("Automation action plan is invalid.")
            for action in plan:
                if not isinstance(action,dict) or set(action)!={"action_type","values"}:
                    raise ValidationError("Action plans may contain only action_type and values; targets are source-bound.")
                action_type=action.get("action_type"); values=action.get("values")
                if action_type not in allowed or not isinstance(values,dict) or set(values)-AUTOMATION_ACTION_FIELDS[action_type]:
                    raise ValidationError("Automation action plan exceeds its allowlist.")
                if action_type=="CREATE_INTERNAL_SUMMARY" and (not isinstance(values.get("body"),str) or not values["body"].strip() or len(values["body"])>10000):
                    raise ValidationError("Automation summary template is invalid.")
                if action_type=="SET_NEXT_ACTION" and (
                    not str(values.get("next_action_type") or "").strip()
                    or not str(values.get("next_action_at") or "").strip()
                    or not isinstance(values.get("next_action_owner_id"),int)
                    or values["next_action_owner_id"]<1
                ):
                    raise ValidationError("Automation next-action template is incomplete.")
                if action_type=="CHANGE_STATUS" and (
                    not str(values.get("status_code") or "").strip()
                    or ("required_values" in values and not isinstance(values["required_values"],dict))
                ):
                    raise ValidationError("Automation status template is incomplete.")

    def materialize_action_plan(self,lead):
        self.ensure_one()
        if not lead or len(lead)!=1 or lead._name!="crm.lead":
            raise AccessError("Automation action source entity scope rejected.")
        lead.ensure_one()
        if not self.active or self.workflow_id.lifecycle_state!="ACTIVE" or not self.workflow_id.active:
            raise AccessError("Campaign automation is not active.")
        if lead.codestra_workflow_id!=self.workflow_id or lead.call_center_campaign_id!=self.workflow_id.campaign_id:
            raise AccessError("Automation action source entity scope rejected.")
        return [{"action_type":action["action_type"],"entity_type":"crm.lead","entity_id":str(lead.id),"values":copy.deepcopy(action["values"])} for action in (self.action_plan or [])]


class CampaignKPI(models.Model):
    _name="codestra.campaign.kpi"; _description="Campaign KPI Definition"
    workflow_id=fields.Many2one("codestra.campaign.workflow",required=True,ondelete="cascade",index=True)
    code=fields.Char(required=True); name=fields.Char(required=True); numerator_status_codes=fields.Json(default=list)
    denominator_status_codes=fields.Json(default=list); aggregation=fields.Selection([("count","Count"),("rate","Rate"),("sum","Sum"),("average","Average")],default="count",required=True)
    active=fields.Boolean(default=True); _kpi_unique=models.Constraint("unique(workflow_id,code)","KPI codes must be unique per workflow.")


class AgentProfile(models.Model):
    _name="codestra.agent.profile"; _description="Human and AI Agent Profile"; _inherit=["mail.thread"]
    agent_uuid=fields.Char(required=True,default=lambda self:str(uuid.uuid4()),copy=False,index=True)
    name=fields.Char(required=True); agent_type=fields.Selection([("HUMAN","Human"),("AI","AI"),("SYSTEM_CANARY","System Canary")],required=True,index=True)
    user_id=fields.Many2one("res.users",ondelete="restrict",index=True)
    campaign_ids=fields.Many2many("call.center.campaign"); team_id=fields.Many2one("call.center.team",ondelete="restrict")
    supervisor_id=fields.Many2one("res.users",ondelete="restrict"); skills=fields.Json(default=list); languages=fields.Json(default=list)
    active=fields.Boolean(default=True); permissions=fields.Json(default=list); daily_capacity=fields.Integer(default=50)
    canary_only=fields.Boolean(default=False,required=True,index=True)
    customer_traffic_allowed=fields.Boolean(default=True,required=True,index=True)
    automation_name=fields.Char(); model_or_service=fields.Char(); task_type=fields.Char()
    human_handoff_count=fields.Integer(default=0,readonly=True); successful_completion_count=fields.Integer(default=0,readonly=True)
    failed_completion_count=fields.Integer(default=0,readonly=True)
    _uuid_unique=models.Constraint("unique(agent_uuid)","Agent UUID must be unique.")
    @api.constrains(
        "agent_type","user_id","automation_name","model_or_service",
        "canary_only","customer_traffic_allowed",
    )
    def _identity(self):
        for row in self:
            if row.agent_type=="HUMAN" and not row.user_id: raise ValidationError("Human agent requires an individual Odoo user.")
            if row.agent_type=="AI" and (not row.automation_name or not row.model_or_service): raise ValidationError("AI agent requires automation and model/service attribution.")
            if row.agent_type=="SYSTEM_CANARY" and (not row.canary_only or row.customer_traffic_allowed):
                raise ValidationError("System canary agents must remain canary-only and customer-traffic denied.")


class CrmLeadCampaignOS(models.Model):
    _inherit="crm.lead"
    codestra_workflow_id=fields.Many2one("codestra.campaign.workflow",ondelete="restrict",index=True)
    codestra_current_status_id=fields.Many2one("codestra.campaign.status",ondelete="restrict",index=True,tracking=True)
    codestra_previous_status_id=fields.Many2one("codestra.campaign.status",ondelete="restrict",readonly=True)
    status_entered_at=fields.Datetime(index=True,readonly=True)
    assigned_agent_profile_id=fields.Many2one("codestra.agent.profile",ondelete="restrict",index=True)
    assigned_agent_type=fields.Selection(related="assigned_agent_profile_id.agent_type",store=True,index=True)
    codestra_supervisor_id=fields.Many2one("res.users",ondelete="restrict",index=True)
    codestra_manager_id=fields.Many2one("res.users",ondelete="restrict",index=True)
    next_action_type=fields.Char(index=True); next_action_at=fields.Datetime(index=True); next_action_owner_id=fields.Many2one("res.users",ondelete="restrict",index=True)
    callback_at=fields.Datetime(index=True); appointment_id=fields.Many2one("codestra.crm.appointment",ondelete="set null")
    appointment_at=fields.Datetime(index=True); last_contact_at=fields.Datetime(index=True); last_call_at=fields.Datetime(index=True)
    last_email_at=fields.Datetime(index=True); last_sms_at=fields.Datetime(index=True); last_note_at=fields.Datetime(index=True)
    source_system=fields.Char(default="odoo",index=True); correlation_id=fields.Char(index=True)
    migration_review_required=fields.Boolean(default=False,index=True)
    test_canary=fields.Boolean(default=False,required=True,index=True)
    requested_documents=fields.Json(default=list); request_date=fields.Date()
    proposal_reference=fields.Char(); proposal_sent_at=fields.Datetime()
    quote_reference=fields.Char(); quote_sent_at=fields.Datetime()
    codestra_timeline_ids=fields.One2many("codestra.activity.timeline","lead_id",readonly=True)
    codestra_communication_ids=fields.One2many("codestra.campaign.communication","lead_id",readonly=True)
    codestra_appointment_ids=fields.One2many("codestra.crm.appointment","lead_id",readonly=True)
    codestra_document_ids=fields.One2many("codestra.campaign.document","lead_id",readonly=True)
    codestra_case_ids=fields.One2many("codestra.contact.center.case","lead_id",readonly=True)
    codestra_data_quality_issue_ids=fields.One2many("codestra.data.quality.issue","lead_id",readonly=True)

    def action_codestra_transition(self,status_id,values=None,override_reason=None,actor_type="HUMAN",automation_id=None,model_or_service=None):
        values=values or {}; target=self.env["codestra.campaign.status"].browse(status_id).exists()
        if not target: raise ValidationError("Unknown campaign status.")
        for lead in self:
            current=lead.codestra_current_status_id
            if target.workflow_id != lead.codestra_workflow_id: raise ValidationError("Cross-campaign status transition denied.")
            allowed=not current or target in current.allowed_next_status_ids
            if not allowed:
                if not override_reason or not self.env.user.has_group("call_center_core.group_call_center_admin"):
                    raise ValidationError("Invalid campaign status transition.")
            missing=[name for name in (target.required_fields or []) if not values.get(name) and not getattr(lead,name,False)]
            if missing: raise ValidationError("Required campaign fields missing: %s"%", ".join(missing))
            if target.requires_note and not values.get("note"): raise ValidationError("This status requires a note.")
            write_values={"codestra_previous_status_id":current.id,"codestra_current_status_id":target.id,"status_entered_at":fields.Datetime.now(),"correlation_id":values.get("correlation_id") or str(uuid.uuid4())}
            # Required business fields supplied with the transition are persisted in
            # the same ORM transaction.  Unknown/control keys are never passed to
            # write(), preserving the API boundary and preventing mass assignment.
            for field_name in target.required_fields or []:
                if field_name in values:
                    write_values[field_name] = values[field_name]
            if target.next_action_required:
                owner=values.get("next_action_owner_id") or lead.user_id.id
                if not owner: raise ValidationError("Next-action owner is required.")
                write_values.update(next_action_type=values.get("next_action_type") or target.default_next_action_type,next_action_owner_id=owner,next_action_at=values.get("next_action_at") or fields.Datetime.now()+timedelta(minutes=target.followup_delay_minutes))
                if not write_values["next_action_type"]: raise ValidationError("Next-action type is required.")
            lead.write(write_values)
            self.env["codestra.activity.timeline"].sudo().create({"event_type":"STATUS_CHANGE","actor_type":actor_type,"actor_id":str(self.env.user.id) if actor_type=="HUMAN" else (automation_id or "system"),"automation_id":automation_id,"model_or_service":model_or_service,"action":"status.override" if override_reason else "status.transition","campaign_id":lead.call_center_campaign_id.id,"lead_id":lead.id,"previous_status_id":current.id,"new_status_id":target.id,"visibility":"INTERNAL","source_system":"odoo","correlation_id":write_values["correlation_id"],"safe_detail":{"override_reason":override_reason} if override_reason else {}})
        return True


class CRMAppointment(models.Model):
    _name="codestra.crm.appointment"; _description="Campaign CRM Appointment"; _inherit=["mail.thread"]
    appointment_uuid=fields.Char(default=lambda self:str(uuid.uuid4()),required=True,copy=False,index=True)
    integration_uuid=fields.Char(related="appointment_uuid",string="Integration UUID",store=True,readonly=True,index=True)
    campaign_id=fields.Many2one("call.center.campaign",required=True,ondelete="restrict",index=True)
    client_id=fields.Many2one("res.partner",ondelete="restrict",index=True); lead_id=fields.Many2one("crm.lead",ondelete="restrict",index=True)
    appointment_type_id=fields.Many2one("codestra.campaign.appointment.type",required=True,ondelete="restrict")
    status=fields.Selection(APPOINTMENT_STATES,default="SCHEDULED",required=True,index=True)
    assigned_agent_id=fields.Many2one("res.users",required=True,ondelete="restrict",index=True); assigned_closer_id=fields.Many2one("res.users",ondelete="restrict")
    supervisor_id=fields.Many2one("res.users",required=True,ondelete="restrict",index=True)
    scheduled_start=fields.Datetime(required=True,index=True); scheduled_end=fields.Datetime(required=True); timezone=fields.Char(required=True)
    customer_confirmation_status=fields.Char(); reminder_status=fields.Char(); meeting_channel=fields.Selection([(x,x.title()) for x in ("PHONE","VIDEO","IN_PERSON","CALLBACK")],required=True)
    outcome=fields.Char(); notes=fields.Text(); next_action=fields.Char(); correlation_id=fields.Char(required=True,index=True)
    _uuid_unique=models.Constraint("unique(appointment_uuid)","Appointment UUID must be unique.")
    @api.constrains("campaign_id","appointment_type_id","scheduled_start","scheduled_end")
    def _scope(self):
        for row in self:
            if row.appointment_type_id.campaign_id and row.appointment_type_id.campaign_id != row.campaign_id: raise ValidationError("Appointment type is not valid for this campaign.")
            if row.scheduled_end <= row.scheduled_start: raise ValidationError("Appointment end must follow start.")

    def _emit_automation(self,event_type,workflow_key,suffix):
        for row in self:
            self.env["codestra.crm.outbox"].create_event(
                event_type=event_type,aggregate=row,aggregate_version=1,
                correlation_id=row.correlation_id,
                idempotency_key=f"appointment:{row.appointment_uuid}:{suffix}",
                campaign=row.campaign_id,
                payload={"appointment_id":row.appointment_uuid,"campaign_id":row.campaign_id.id,
                         "lead_id":row.lead_id.id,"workflow_key":workflow_key,
                         "scheduled_start":fields.Datetime.to_string(row.scheduled_start)})

    def action_schedule_confirmation(self):
        self._emit_automation("crm.appointment.created.v1","appointment_confirmation","confirmation")
        return True

    @api.model
    def run_reminders(self):
        now_value=fields.Datetime.now(); emitted=0
        for minutes,key in ((1440,"appointment_24h_reminder"),(60,"appointment_1h_reminder")):
            lower=now_value+timedelta(minutes=minutes-5); upper=now_value+timedelta(minutes=minutes+5)
            rows=self.search([("status","in",("SCHEDULED","CONFIRMED","REMINDER_SENT")),
                              ("scheduled_start",">=",lower),("scheduled_start","<=",upper)])
            for row in rows:
                row._emit_automation("crm.appointment.reminder.due.v1",key,f"reminder-{minutes}"); emitted+=1
        return emitted

    def action_complete(self,outcome=None,next_action=None):
        self.write({"status":"COMPLETED","outcome":outcome,"next_action":next_action})
        self._emit_automation("crm.appointment.completed.v1","appointment_completed","completed")
        return True

    def action_customer_no_show(self):
        self.write({"status":"CUSTOMER_NO_SHOW"})
        self._emit_automation("crm.appointment.customer_no_show.v1","customer_no_show","customer-no-show")
        return True

    def action_agent_no_show(self):
        self.write({"status":"AGENT_NO_SHOW"})
        self._emit_automation("crm.appointment.agent_no_show.v1","supervisor_escalation","agent-no-show")
        return True


class ActivityTimeline(models.Model):
    _name="codestra.activity.timeline"; _description="Immutable Unified CRM Timeline"; _order="occurred_at desc"; _log_access=False
    event_uuid=fields.Char(default=lambda self:str(uuid.uuid4()),required=True,index=True)
    event_type=fields.Selection([(x,x.replace("_"," ").title()) for x in ("CALL","EMAIL","SMS","APPOINTMENT","INTERNAL_NOTE","SYSTEM_EVENT","AI_ACTION","STATUS_CHANGE","ASSIGNMENT_CHANGE","TRANSFER","DOCUMENT_EVENT","WEBHOOK_EVENT")],required=True,index=True)
    actor_type=fields.Selection(ACTOR_TYPES,required=True,index=True); actor_id=fields.Char(required=True,index=True)
    automation_id=fields.Char(); model_or_service=fields.Char(); action=fields.Char(required=True)
    occurred_at=fields.Datetime(default=fields.Datetime.now,required=True,index=True); campaign_id=fields.Many2one("call.center.campaign",required=True,ondelete="restrict",index=True)
    client_id=fields.Many2one("res.partner",ondelete="restrict",index=True); lead_id=fields.Many2one("crm.lead",ondelete="restrict",index=True)
    previous_status_id=fields.Many2one("codestra.campaign.status",ondelete="restrict"); new_status_id=fields.Many2one("codestra.campaign.status",ondelete="restrict")
    visibility=fields.Selection([(x,x.title()) for x in ("CUSTOMER","INTERNAL","SUPERVISOR","QA","COMPLIANCE")],required=True,index=True)
    source_system=fields.Char(required=True); correlation_id=fields.Char(required=True,index=True); safe_detail=fields.Json(default=dict)
    _uuid_unique=models.Constraint("unique(event_uuid)","Timeline event UUID must be unique.")
    def write(self,vals): raise AccessError("Timeline is append-only.")
    def unlink(self): raise AccessError("Timeline is append-only.")


class CampaignNote(models.Model):
    _name="codestra.campaign.note"; _description="Campaign-Scoped CRM Note"; _order="created_at desc"; _log_access=False
    note_uuid=fields.Char(default=lambda self:str(uuid.uuid4()),required=True,copy=False,index=True)
    campaign_id=fields.Many2one("call.center.campaign",required=True,ondelete="restrict",index=True)
    lead_id=fields.Many2one("crm.lead",required=True,ondelete="cascade",index=True)
    author_id=fields.Many2one("res.users",required=True,default=lambda self:self.env.user,ondelete="restrict",index=True)
    actor_type=fields.Selection(ACTOR_TYPES,required=True,default="HUMAN",index=True)
    actor_id=fields.Char(required=True,default=lambda self:str(self.env.user.id or "system"),index=True)
    visibility=fields.Selection(NOTE_VISIBILITIES,required=True,default="INTERNAL",index=True)
    body=fields.Text(required=True); correlation_id=fields.Char(required=True,index=True)
    created_at=fields.Datetime(default=fields.Datetime.now,required=True,index=True)
    _uuid_unique=models.Constraint("unique(note_uuid)","Note UUID must be unique.")

    @api.constrains("campaign_id","lead_id")
    def _campaign_scope(self):
        for row in self:
            if row.lead_id.call_center_campaign_id != row.campaign_id:
                raise ValidationError("Note and lead must share a campaign.")

    @api.model_create_multi
    def create(self,vals_list):
        rows=super().create(vals_list)
        for row in rows:
            self.env["codestra.activity.timeline"].sudo().create({
                "event_type":"INTERNAL_NOTE","actor_type":row.actor_type,"actor_id":row.actor_id,
                "action":"note.created","campaign_id":row.campaign_id.id,"lead_id":row.lead_id.id,
                "visibility":"CUSTOMER" if row.visibility=="CUSTOMER_VISIBLE" else row.visibility,
                "source_system":"odoo","correlation_id":row.correlation_id,
                "safe_detail":{"note_uuid":row.note_uuid,"visibility":row.visibility}})
            row.lead_id.last_note_at=fields.Datetime.now()
        return rows

    def unlink(self): raise AccessError("CRM notes are retained for audit.")


class CampaignTransferPolicy(models.Model):
    _name="codestra.campaign.transfer.policy"; _description="Campaign Transfer Policy"
    campaign_id=fields.Many2one("call.center.campaign",required=True,ondelete="cascade",index=True)
    transfer_type=fields.Selection([(x,x.replace("_"," ").title()) for x in
      ("AGENT_TO_CLOSER","AGENT_TO_SUPERVISOR","AGENT_TO_SUPPORT")],required=True)
    target_campaign_id=fields.Many2one("call.center.campaign",ondelete="restrict",index=True)
    allow_cross_campaign=fields.Boolean(default=False); active=fields.Boolean(default=True)
    _policy_unique=models.Constraint("unique(campaign_id,transfer_type,target_campaign_id)","Transfer policy already exists.")

    @api.constrains("campaign_id","target_campaign_id","allow_cross_campaign")
    def _cross_campaign(self):
        for row in self:
            if row.target_campaign_id and row.target_campaign_id != row.campaign_id and not row.allow_cross_campaign:
                raise ValidationError("Cross-campaign transfer requires explicit approval.")

    @api.model
    def authorize(self,campaign,transfer_type,target_campaign=None):
        target_campaign=target_campaign or campaign
        policy=self.search([("campaign_id","=",campaign.id),("transfer_type","=",transfer_type),
                            ("target_campaign_id","in",(False,target_campaign.id)),("active","=",True)],limit=1)
        if not policy or (target_campaign != campaign and not policy.allow_cross_campaign):
            raise AccessError("Unauthorized campaign transfer.")
        return policy


class CallEvent(models.Model):
    _name="codestra.call.event"; _description="Normalized VICIdial Call Event"; _order="started_at desc"
    call_id=fields.Char(required=True,index=True); vicidial_lead_id=fields.Char(index=True)
    campaign_id=fields.Many2one("call.center.campaign",required=True,ondelete="restrict",index=True); agent_id=fields.Many2one("codestra.agent.profile",ondelete="restrict",index=True)
    started_at=fields.Datetime(required=True,index=True); answered_at=fields.Datetime(); ended_at=fields.Datetime()
    duration=fields.Integer(); talk_time=fields.Integer(); disposition=fields.Char(index=True); recording_reference=fields.Char()
    transfer_type=fields.Selection([(x,x.replace("_"," ").title()) for x in ("AGENT_TO_CLOSER","AGENT_TO_SUPERVISOR","AGENT_TO_SUPPORT")]); transfer_target=fields.Char()
    callback_created=fields.Boolean(); correlation_id=fields.Char(required=True,index=True); source_event_id=fields.Char(required=True,index=True)
    _event_unique=models.Constraint("unique(source_event_id)","Call events must be idempotent.")


class AgentPerformance(models.Model):
    _name="codestra.agent.performance"; _description="Campaign Agent Performance Snapshot"; _order="period_start desc"
    agent_id=fields.Many2one("codestra.agent.profile",required=True,ondelete="cascade",index=True); campaign_id=fields.Many2one("call.center.campaign",required=True,ondelete="cascade",index=True)
    period_start=fields.Date(required=True,index=True); period_end=fields.Date(required=True)
    metrics=fields.Json(default=dict,readonly=True); leads_assigned=fields.Integer(readonly=True); calls_attempted=fields.Integer(readonly=True)
    contacts=fields.Integer(readonly=True); qualified=fields.Integer(readonly=True); callbacks_overdue=fields.Integer(readonly=True)
    appointments_set=fields.Integer(readonly=True); emails_sent=fields.Integer(readonly=True); replies_received=fields.Integer(readonly=True)
    followup_sla_met_percent=fields.Float(readonly=True); overdue_followups=fields.Integer(readonly=True); won=fields.Integer(readonly=True); lost=fields.Integer(readonly=True)
    qa_score=fields.Float(readonly=True); compliance_flags=fields.Integer(readonly=True); current_workload=fields.Integer(readonly=True)
    _snapshot_unique=models.Constraint("unique(agent_id,campaign_id,period_start,period_end)","Performance snapshot already exists.")


class DailyOperationsReport(models.Model):
    _name="codestra.daily.operations.report"; _description="Campaign Daily Operations Report"; _order="report_date desc,campaign_id"
    report_date=fields.Date(required=True,index=True); campaign_id=fields.Many2one("call.center.campaign",required=True,ondelete="cascade",index=True)
    integration_uuid=fields.Char(default=lambda self:str(uuid.uuid4()),required=True,copy=False,readonly=True,index=True)
    business_unit_id=fields.Many2one(related="campaign_id.business_unit_id",store=True,index=True)
    metrics=fields.Json(default=dict,readonly=True); generated_at=fields.Datetime(required=True,default=fields.Datetime.now,readonly=True)
    correlation_id=fields.Char(required=True,index=True,readonly=True); source_watermark=fields.Char(readonly=True)
    _report_unique=models.Constraint("unique(report_date,campaign_id)","Daily campaign report already exists.")

    @api.model
    def generate(self,report_date=None):
        report_date=fields.Date.to_date(report_date or fields.Date.context_today(self))
        generated=[]
        workflows=self.env["codestra.campaign.workflow"].search([("active","=",True),("campaign_id","!=",False)])
        for workflow in workflows:
            campaign=workflow.campaign_id
            leads=self.env["crm.lead"].search([("call_center_campaign_id","=",campaign.id),("active","in",(True,False))])
            appointments=self.env["codestra.crm.appointment"].search([("campaign_id","=",campaign.id),
                ("scheduled_start",">=",fields.Datetime.to_datetime(report_date)),
                ("scheduled_start","<",fields.Datetime.to_datetime(report_date)+timedelta(days=1))])
            status_counts={}
            for lead in leads:
                code=lead.codestra_current_status_id.code or "MIGRATION_REVIEW_REQUIRED"
                status_counts[code]=status_counts.get(code,0)+1
            metrics={"leads_total":len(leads),"unworked":len(leads.filtered(lambda x:not x.last_contact_at)),
                     "followups_due":len(leads.filtered(lambda x:x.next_action_at and x.next_action_at<=fields.Datetime.now())),
                     "appointments":len(appointments),"appointment_no_shows":len(appointments.filtered(lambda x:x.status in ("CUSTOMER_NO_SHOW","AGENT_NO_SHOW"))),
                     "status_counts":status_counts,"kpis":[k.code for k in self.env["codestra.campaign.kpi"].search([("workflow_id","=",workflow.id),("active","=",True)])]}
            row=self.search([("report_date","=",report_date),("campaign_id","=",campaign.id)],limit=1)
            correlation=row.correlation_id if row else str(uuid.uuid4())
            values={"report_date":report_date,"campaign_id":campaign.id,"metrics":metrics,"correlation_id":correlation,"source_watermark":fields.Datetime.to_string(fields.Datetime.now())}
            if row: row.write(values)
            else: row=self.create(values)
            generated.append(row.id)
            self.env["codestra.crm.outbox"].create_event(event_type="crm.daily_report.ready.v1",aggregate=row,
              aggregate_version=1,correlation_id=correlation,idempotency_key=f"daily-report:{campaign.id}:{report_date}",campaign=campaign,
              payload={"report_id":row.id,"campaign_id":campaign.id,"report_date":str(report_date)})
        return generated


class CampaignSLAService(models.AbstractModel):
    _name="codestra.campaign.sla.service"; _description="Campaign SLA Escalation Service"
    @api.model
    def run(self):
        now_value=fields.Datetime.now(); leads=self.env["crm.lead"].search([("codestra_current_status_id.next_action_required","=",True),("next_action_at","<",now_value),("active","=",True)])
        for lead in leads:
            rule=self.env["codestra.campaign.followup.rule"].search([("status_id","=",lead.codestra_current_status_id.id),("active","=",True)],limit=1)
            if not rule: continue
            overdue=(now_value-lead.next_action_at).total_seconds()/60
            level="agent"
            if overdue>=rule.manager_escalation_minutes: level="manager"
            elif overdue>=rule.supervisor_escalation_minutes: level="supervisor"
            key=f"sla:{lead.id}:{lead.codestra_current_status_id.id}:{level}:{lead.next_action_at.isoformat()}"
            self.env["codestra.crm.outbox"].create_event(event_type=f"crm.sla.{level}.v1",aggregate=lead,aggregate_version=1,correlation_id=lead.correlation_id or str(uuid.uuid4()),idempotency_key=key,campaign=lead.call_center_campaign_id,payload={"lead_id":lead.id,"campaign_id":lead.call_center_campaign_id.id,"level":level,"due_at":fields.Datetime.to_string(lead.next_action_at)})
        return len(leads)
