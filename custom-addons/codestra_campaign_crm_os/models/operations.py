import uuid
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


DOCUMENT_STATES = [(value, value.replace("_", " ").title()) for value in (
    "REQUIRED", "REQUESTED", "RECEIVED", "INVALID", "EXPIRED", "APPROVED", "WAIVED"
)]


class AutomationActionReceipt(models.Model):
    _name = "codestra.automation.action.receipt"
    _description = "Immutable Automation Action Idempotency Receipt"
    _log_access = False

    receipt_uuid = fields.Char(default=lambda self: str(uuid.uuid4()), required=True, copy=False, readonly=True, index=True)
    idempotency_key = fields.Char(required=True, readonly=True, index=True)
    event_id = fields.Char(required=True, readonly=True, index=True)
    execution_id = fields.Char(required=True, readonly=True, index=True)
    request_hash = fields.Char(required=True, readonly=True)
    correlation_id = fields.Char(required=True, readonly=True, index=True)
    campaign_public_id = fields.Char(required=True, readonly=True, index=True)
    response_json = fields.Text(required=True, readonly=True)
    applied_at = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True)
    _receipt_unique = models.Constraint("unique(receipt_uuid)", "Automation receipt UUID must be unique.")
    _idempotency_unique = models.Constraint("unique(idempotency_key)", "Automation action was already received.")

    def write(self, values):
        if set(values) != {"response_json"} or not self.env.context.get("codestra_receipt_finalize"):
            raise AccessError("Automation action receipts are immutable.")
        return super().write(values)

    def unlink(self):
        raise AccessError("Automation action receipts cannot be deleted.")


class CampaignActionService(models.AbstractModel):
    _name = "codestra.campaign.action.service"
    _description = "Authorized Campaign Automation Action Service"

    _ACTION_FIELDS = {
        "CREATE_INTERNAL_SUMMARY": {"body"},
        "SET_NEXT_ACTION": {"next_action_type", "next_action_at", "next_action_owner_id"},
        "CHANGE_STATUS": {"status_code", "required_values"},
    }

    @api.model
    def apply(self, document):
        campaign = self.env["call.center.campaign"].search(
            [("code", "=", document["campaign_public_id"])], limit=1
        )
        if not campaign or campaign.business_unit_id.code != document["business_unit_public_id"]:
            raise AccessError("Campaign scope rejected.")
        workflow = self.env["codestra.campaign.workflow"].with_context(active_test=False).search([
            ("campaign_id", "=", campaign.id), ("lifecycle_state", "=", "ACTIVE"),
            ("active", "=", True),
        ], limit=1)
        automation = self.env["codestra.campaign.automation"].with_context(active_test=False).search([
            ("workflow_id", "=", workflow.id),
            ("n8n_workflow_key", "=", document["workflow_key"]),
            ("active", "=", True),
        ], limit=1)
        if not workflow or not automation:
            raise AccessError("Campaign automation is not active.")
        actor = None
        if document["actor_type"] == "AI":
            actor = self.env["codestra.agent.profile"].with_context(active_test=False).search([
                ("agent_uuid", "=", document["actor_id"]), ("agent_type", "=", "AI"),
                ("active", "=", True), ("campaign_ids", "in", campaign.id),
            ], limit=1)
            if not actor:
                raise AccessError("AI actor scope rejected.")
        applied = []
        for position, action in enumerate(document["actions"]):
            expected = {"action_type", "entity_type", "entity_id", "values"}
            if not isinstance(action, dict) or set(action) != expected:
                raise ValidationError("Invalid automation action envelope.")
            action_type = action["action_type"]
            if action_type not in self._ACTION_FIELDS:
                raise AccessError("Automation action is not supported.")
            if actor and action_type not in (actor.permissions or []):
                raise AccessError("AI action is not permitted.")
            if action["entity_type"] != "crm.lead" or not str(action["entity_id"]).isdigit():
                raise ValidationError("Automation action entity is invalid.")
            values = action["values"]
            if not isinstance(values, dict) or set(values) - self._ACTION_FIELDS[action_type]:
                raise ValidationError("Unexpected automation action values.")
            lead = self.env["crm.lead"].browse(int(action["entity_id"])).exists()
            if not lead or lead.call_center_campaign_id != campaign or lead.codestra_workflow_id != workflow:
                raise AccessError("Automation action entity scope rejected.")
            self._apply_one(lead, action_type, values, document)
            applied.append({"position": position, "action_type": action_type, "entity_id": str(lead.id)})
        return {
            "status": "APPLIED", "event_id": document["event_id"],
            "execution_id": document["execution_id"],
            "correlation_id": document["correlation_id"], "applied_actions": applied,
        }

    @api.model
    def _apply_one(self, lead, action_type, values, document):
        if action_type == "CHANGE_STATUS":
            status = self.env["codestra.campaign.status"].search([
                ("workflow_id", "=", lead.codestra_workflow_id.id),
                ("code", "=", values.get("status_code")),
            ], limit=1)
            transition_values = dict(values.get("required_values") or {})
            transition_values["correlation_id"] = document["correlation_id"]
            return lead.action_codestra_transition(
                status.id, transition_values, actor_type=document["actor_type"],
                automation_id=document["execution_id"], model_or_service=document["workflow_key"],
            )
        if action_type == "SET_NEXT_ACTION":
            required = {"next_action_type", "next_action_at", "next_action_owner_id"}
            if not required.issubset(values):
                raise ValidationError("Next action values are incomplete.")
            lead.write({name: values[name] for name in required})
            self.env["codestra.activity.timeline"].create({
                "event_type": "AI_ACTION" if document["actor_type"] == "AI" else "SYSTEM_EVENT",
                "actor_type": document["actor_type"], "actor_id": document["actor_id"],
                "automation_id": document["execution_id"], "model_or_service": document["workflow_key"],
                "action": "next_action.set", "campaign_id": lead.call_center_campaign_id.id,
                "lead_id": lead.id, "visibility": "INTERNAL", "source_system": "middleware",
                "correlation_id": document["correlation_id"],
                "safe_detail": {"next_action_type": values["next_action_type"], "next_action_at": values["next_action_at"]},
            })
            return True
        body = str(values.get("body") or "").strip()
        if not body or len(body) > 10000:
            raise ValidationError("Internal summary body is invalid.")
        self.env["codestra.campaign.note"].create({
            "campaign_id": lead.call_center_campaign_id.id, "lead_id": lead.id,
            "author_id": self.env.ref("base.user_admin").id,
            "actor_type": document["actor_type"], "actor_id": document["actor_id"],
            "visibility": "INTERNAL", "body": body,
            "correlation_id": document["correlation_id"],
        })
        return True


class CRMOutbox(models.Model):
    _name = "codestra.crm.outbox"
    _description = "Immutable Campaign CRM Transactional Outbox"
    _order = "created_at, id"

    event_uuid = fields.Char(default=lambda self: str(uuid.uuid4()), required=True, copy=False, readonly=True, index=True)
    event_type = fields.Char(required=True, readonly=True, index=True)
    schema_version = fields.Char(default="1", required=True, readonly=True)
    aggregate_type = fields.Char(required=True, readonly=True, index=True)
    aggregate_record_id = fields.Integer(required=True, readonly=True, index=True)
    aggregate_uuid = fields.Char(required=True, readonly=True, index=True)
    aggregate_version = fields.Integer(required=True, readonly=True)
    campaign_id = fields.Many2one("call.center.campaign", required=True, ondelete="restrict", readonly=True, index=True)
    correlation_id = fields.Char(required=True, readonly=True, index=True)
    idempotency_key = fields.Char(required=True, readonly=True, index=True)
    payload = fields.Json(required=True, readonly=True)
    state = fields.Selection([
        ("PENDING", "Pending"), ("PROCESSING", "Processing"),
        ("DELIVERED", "Delivered"), ("RETRY", "Retry"),
        ("DEAD_LETTER", "Dead Letter"),
    ], default="PENDING", required=True, readonly=True, index=True)
    attempt_count = fields.Integer(default=0, required=True, readonly=True)
    next_attempt_at = fields.Datetime(readonly=True, index=True)
    last_error_safe = fields.Char(readonly=True)
    created_at = fields.Datetime(default=fields.Datetime.now, required=True, readonly=True, index=True)
    delivered_at = fields.Datetime(readonly=True)
    _event_unique = models.Constraint("unique(event_uuid)", "CRM event UUID must be unique.")
    _idempotency_unique = models.Constraint("unique(idempotency_key)", "CRM outbox idempotency key already exists.")
    _attempt_nonnegative = models.Constraint("check(attempt_count >= 0)", "Attempt count cannot be negative.")

    @api.model
    def create_event(self, *, event_type, aggregate, aggregate_version, correlation_id,
                     idempotency_key, campaign, payload):
        payload=dict(payload or {})
        if "authorized_actions" in payload:
            raise ValidationError("Authorized actions must be materialized from campaign automation configuration.")
        registry_key=payload.get("workflow_key")
        if registry_key:
            workflow=self.env["codestra.campaign.workflow"].sudo().with_context(active_test=False).search([
                ("campaign_id","=",campaign.id),("active","=",True),("lifecycle_state","=","ACTIVE")
            ],limit=1)
            automation=self.env["codestra.campaign.automation"].sudo().with_context(active_test=False).search([
                ("workflow_id","=",workflow.id),("key","=",registry_key),("active","=",True)
            ],limit=1) if workflow else self.env["codestra.campaign.automation"]
            if automation:
                lead=aggregate if aggregate._name=="crm.lead" else self.env["crm.lead"].browse(int(payload.get("lead_id") or 0)).exists()
                payload["workflow_key"]=automation.n8n_workflow_key
                payload["authorized_actions"]=automation.materialize_action_plan(lead)
        existing = self.sudo().search([("idempotency_key", "=", idempotency_key)], limit=1)
        if existing:
            immutable = {
                "event_type": event_type,
                "aggregate_type": aggregate._name,
                "aggregate_record_id": aggregate.id,
                "aggregate_version": aggregate_version,
                "campaign_id": campaign.id,
                "correlation_id": correlation_id,
                "payload": payload,
            }
            for name, value in immutable.items():
                current = existing[name]
                if name == "campaign_id":
                    current = current.id
                if current != value:
                    raise ValidationError("CRM outbox idempotency conflict.")
            return existing
        aggregate_uuid = next((aggregate[name] for name in (
            "appointment_uuid", "report_uuid", "queue_uuid", "communication_uuid", "id"
        ) if name in aggregate._fields and aggregate[name]), str(aggregate.id))
        return super(CRMOutbox, self.sudo().with_context(
            codestra_crm_outbox_internal=True
        )).create({
            "event_type": event_type, "aggregate_type": aggregate._name,
            "aggregate_record_id": aggregate.id, "aggregate_uuid": str(aggregate_uuid),
            "aggregate_version": aggregate_version, "campaign_id": campaign.id,
            "correlation_id": correlation_id, "idempotency_key": idempotency_key,
            "payload": payload,
        })

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("codestra_crm_outbox_internal"):
            raise AccessError("CRM outbox records require the internal producer contract.")
        return super().create(vals_list)

    def write(self, vals):
        allowed = {"state", "attempt_count", "next_attempt_at", "last_error_safe", "delivered_at"}
        if set(vals) - allowed or not self.env.context.get("codestra_crm_outbox_worker"):
            raise AccessError("CRM outbox identity and payload are immutable.")
        return super().write(vals)

    def unlink(self):
        raise AccessError("CRM outbox history cannot be deleted.")


class CampaignDocumentDefinition(models.Model):
    _name = "codestra.campaign.document.definition"
    _description = "Campaign Document Checklist Definition"

    workflow_id = fields.Many2one("codestra.campaign.workflow", required=True, ondelete="cascade", index=True)
    document_type = fields.Char(required=True, index=True)
    required_at_status_id = fields.Many2one("codestra.campaign.status", required=True, ondelete="restrict")
    expiration_days = fields.Integer(default=0)
    validation_required = fields.Boolean(default=True)
    approver_group_xmlid = fields.Char()
    reminder_schedule_minutes = fields.Json(default=list)
    active = fields.Boolean(default=True)
    _unique = models.Constraint("unique(workflow_id, document_type)", "Document type must be unique per workflow.")

    @api.constrains("workflow_id", "required_at_status_id", "expiration_days")
    def _check_scope(self):
        for row in self:
            if row.required_at_status_id.workflow_id != row.workflow_id:
                raise ValidationError("Document definition and required status must share a workflow.")
            if row.expiration_days < 0:
                raise ValidationError("Document expiration cannot be negative.")


class CampaignDocument(models.Model):
    _name = "codestra.campaign.document"
    _description = "Campaign Client Document Checklist Item"
    _order = "lead_id, definition_id"

    document_uuid = fields.Char(default=lambda self: str(uuid.uuid4()), required=True, copy=False, index=True)
    definition_id = fields.Many2one("codestra.campaign.document.definition", required=True, ondelete="restrict")
    campaign_id = fields.Many2one("call.center.campaign", required=True, ondelete="restrict", index=True)
    lead_id = fields.Many2one("crm.lead", required=True, ondelete="cascade", index=True)
    state = fields.Selection(DOCUMENT_STATES, required=True, default="REQUIRED", index=True)
    requested_at = fields.Datetime()
    received_at = fields.Datetime()
    expires_at = fields.Datetime()
    approved_by_id = fields.Many2one("res.users", ondelete="restrict")
    approved_at = fields.Datetime()
    protected_reference = fields.Char(help="Protected document reference; document bytes are not duplicated here.")
    correlation_id = fields.Char(required=True, index=True)
    _uuid_unique = models.Constraint("unique(document_uuid)", "Document UUID must be unique.")
    _item_unique = models.Constraint("unique(lead_id, definition_id)", "A checklist item already exists for this lead.")

    @api.constrains("campaign_id", "lead_id", "definition_id")
    def _check_scope(self):
        for row in self:
            if row.lead_id.call_center_campaign_id != row.campaign_id:
                raise ValidationError("Document and lead must share a campaign.")
            if row.definition_id.workflow_id != row.lead_id.codestra_workflow_id:
                raise ValidationError("Document definition is not authorized for this lead workflow.")

    def action_set_state(self, state, protected_reference=None):
        allowed = dict(DOCUMENT_STATES)
        if state not in allowed:
            raise ValidationError("Unknown document state.")
        now = fields.Datetime.now()
        for row in self:
            values = {"state": state}
            if state == "REQUESTED": values["requested_at"] = now
            if state == "RECEIVED": values.update(received_at=now, protected_reference=protected_reference)
            if state in ("APPROVED", "WAIVED"):
                if not self.env.user.has_group("call_center_core.group_call_center_supervisor") and not self.env.user.has_group("call_center_core.group_call_center_admin"):
                    raise AccessError("Document approval requires supervisor or administrator authority.")
                values.update(approved_by_id=self.env.user.id, approved_at=now)
            row.write(values)
            self.env["codestra.activity.timeline"].sudo().create({
                "event_type": "DOCUMENT_EVENT", "actor_type": "HUMAN", "actor_id": str(self.env.user.id),
                "action": f"document.{state.lower()}", "campaign_id": row.campaign_id.id,
                "lead_id": row.lead_id.id, "visibility": "INTERNAL", "source_system": "odoo",
                "correlation_id": row.correlation_id,
                "safe_detail": {"document_uuid": row.document_uuid, "document_type": row.definition_id.document_type},
            })
        return True


class CampaignPlaybook(models.Model):
    _name = "codestra.campaign.playbook"
    _description = "Campaign Status Playbook"

    status_id = fields.Many2one("codestra.campaign.status", required=True, ondelete="cascade", index=True)
    agent_objective = fields.Text(required=True)
    suggested_opening = fields.Text()
    required_questions = fields.Json(default=list)
    objections = fields.Json(default=list)
    required_disclosures = fields.Json(default=list)
    required_data = fields.Json(default=list)
    recommended_next_action = fields.Char()
    knowledge_references = fields.Json(default=list)
    active = fields.Boolean(default=True)
    _status_unique = models.Constraint("unique(status_id)", "A status has one authoritative playbook.")


class WorkQueueItem(models.Model):
    _name = "codestra.work.queue.item"
    _description = "Agent My Work Today Queue Item"
    _order = "priority asc, due_at asc, id asc"

    queue_uuid = fields.Char(default=lambda self: str(uuid.uuid4()), required=True, copy=False, index=True)
    lead_id = fields.Many2one("crm.lead", required=True, ondelete="cascade", index=True)
    campaign_id = fields.Many2one(related="lead_id.call_center_campaign_id", store=True, index=True)
    owner_id = fields.Many2one("res.users", required=True, ondelete="restrict", index=True)
    reason = fields.Selection([(str(n), label) for n, label in (
        (1, "Overdue callback"), (2, "Appointment starting soon"), (3, "SLA-breached follow-up"),
        (4, "Customer reply"), (5, "Document review"), (6, "New assigned lead"),
        (7, "Scheduled follow-up"), (8, "Nurture"))], required=True, index=True)
    next_action = fields.Char(required=True)
    due_at = fields.Datetime(required=True, index=True)
    priority = fields.Integer(required=True, default=8, index=True)
    state = fields.Selection([("OPEN", "Open"), ("COMPLETED", "Completed"), ("RESCHEDULED", "Rescheduled")], default="OPEN", required=True, index=True)
    correlation_id = fields.Char(required=True, index=True)
    _uuid_unique = models.Constraint("unique(queue_uuid)", "Queue UUID must be unique.")
    _active_action_unique = models.Constraint("unique(lead_id, next_action, due_at)", "Queue action already exists.")

    def action_complete(self):
        self.write({"state": "COMPLETED"})
        return True

    def action_reschedule(self, due_at):
        if fields.Datetime.to_datetime(due_at) <= fields.Datetime.now():
            raise ValidationError("Rescheduled work must be due in the future.")
        self.write({"state": "RESCHEDULED", "due_at": due_at})
        return True


class CampaignCommunication(models.Model):
    _name = "codestra.campaign.communication"
    _description = "Campaign Email and SMS Correspondence"
    _order = "occurred_at desc"

    communication_uuid = fields.Char(default=lambda self: str(uuid.uuid4()), required=True, copy=False, index=True)
    channel = fields.Selection([("EMAIL", "Email"), ("SMS", "SMS")], required=True, index=True)
    direction = fields.Selection([("INBOUND", "Inbound"), ("OUTBOUND", "Outbound")], required=True, index=True)
    campaign_id = fields.Many2one("call.center.campaign", required=True, ondelete="restrict", index=True)
    lead_id = fields.Many2one("crm.lead", required=True, ondelete="cascade", index=True)
    status = fields.Selection([(x, x.title()) for x in ("QUEUED", "SUBMITTED", "SENT", "DELIVERED", "BOUNCED", "FAILED", "REPLIED", "OPTED_OUT")], required=True, default="QUEUED", index=True)
    provider_reference = fields.Char(index=True)
    message_id = fields.Char(index=True)
    in_reply_to = fields.Char(index=True)
    references = fields.Json(default=list)
    consent_basis = fields.Char()
    occurred_at = fields.Datetime(default=fields.Datetime.now, required=True, index=True)
    correlation_id = fields.Char(required=True, index=True)
    idempotency_key = fields.Char(required=True, index=True)
    _uuid_unique = models.Constraint("unique(communication_uuid)", "Communication UUID must be unique.")
    _idempotency_unique = models.Constraint("unique(idempotency_key)", "Communication idempotency key already exists.")

    @api.constrains("campaign_id", "lead_id", "channel", "direction", "consent_basis")
    def _check_policy(self):
        for row in self:
            if row.lead_id.call_center_campaign_id != row.campaign_id:
                raise ValidationError("Communication and lead must share a campaign.")
            if row.channel == "SMS" and row.direction == "OUTBOUND" and not row.consent_basis:
                raise ValidationError("Outbound SMS requires a recorded consent basis.")


class AITask(models.Model):
    _name = "codestra.ai.task"
    _description = "Bounded Campaign AI Task"

    task_uuid = fields.Char(default=lambda self: str(uuid.uuid4()), required=True, copy=False, index=True)
    agent_id = fields.Many2one("codestra.agent.profile", required=True, ondelete="restrict", index=True)
    lead_id = fields.Many2one("crm.lead", required=True, ondelete="cascade", index=True)
    task_type = fields.Char(required=True, index=True)
    allowed_actions = fields.Json(default=list)
    requested_action = fields.Char(index=True)
    state = fields.Selection([("PENDING", "Pending"), ("COMPLETED", "Completed"), ("DENIED", "Denied"), ("HUMAN_HANDOFF", "Human Handoff"), ("FAILED", "Failed")], default="PENDING", required=True, index=True)
    result = fields.Json(default=dict)
    correlation_id = fields.Char(required=True, index=True)
    _uuid_unique = models.Constraint("unique(task_uuid)", "AI task UUID must be unique.")

    @api.constrains("agent_id")
    def _ai_only(self):
        for row in self:
            if row.agent_id.agent_type != "AI":
                raise ValidationError("Only an AI agent profile can own an AI task.")

    def action_apply_result(self, action, result=None):
        for row in self:
            if action not in (row.allowed_actions or []) or action not in (row.agent_id.permissions or []):
                row.write({"requested_action": action, "state": "DENIED", "result": {}})
                return False
            row.write({"requested_action": action, "state": "COMPLETED", "result": result or {}})
            row.agent_id.sudo().write({"successful_completion_count": row.agent_id.successful_completion_count + 1})
        return True

    def action_human_handoff(self):
        for row in self:
            row.write({"state": "HUMAN_HANDOFF"})
            row.agent_id.sudo().write({"human_handoff_count": row.agent_id.human_handoff_count + 1})
        return True


class LeadDistributionRule(models.Model):
    _name="codestra.lead.distribution.rule"; _description="Campaign Lead Distribution Rule"
    campaign_id=fields.Many2one("call.center.campaign",required=True,ondelete="cascade",index=True)
    strategy=fields.Selection([(x,x.replace("_"," ").title()) for x in ("ROUND_ROBIN","WEIGHTED_ROUND_ROBIN","SKILL_BASED","LOAD_BALANCED","MANUAL","AI_FIRST","HUMAN_ONLY")],required=True,default="ROUND_ROBIN")
    eligible_agent_ids=fields.Many2many("codestra.agent.profile"); required_skills=fields.Json(default=list); required_languages=fields.Json(default=list)
    maximum_open_items=fields.Integer(default=50); next_sequence=fields.Integer(default=0,readonly=True); active=fields.Boolean(default=True)
    _campaign_unique=models.Constraint("unique(campaign_id)","A campaign has one authoritative distribution rule.")

    def assign(self,lead):
        self.ensure_one(); lead.ensure_one()
        if lead.call_center_campaign_id!=self.campaign_id: raise ValidationError("Distribution rule and lead campaign mismatch.")
        if self.strategy=="MANUAL": raise ValidationError("Manual distribution requires an explicit agent selection.")
        profiles=self.eligible_agent_ids.filtered(lambda row:row.active and self.campaign_id in row.campaign_ids)
        if self.strategy=="HUMAN_ONLY": profiles=profiles.filtered(lambda row:row.agent_type=="HUMAN")
        skills,languages=set(self.required_skills or []),set(self.required_languages or [])
        if skills: profiles=profiles.filtered(lambda row:skills.issubset(set(row.skills or [])))
        if languages: profiles=profiles.filtered(lambda row:languages.intersection(set(row.languages or [])))
        Queue=self.env["codestra.work.queue.item"]; workloads={row.id:Queue.search_count([("owner_id","=",row.user_id.id),("state","=","OPEN")]) for row in profiles if row.user_id}
        profiles=profiles.filtered(lambda row:row.user_id and workloads.get(row.id,0)<min(row.daily_capacity,self.maximum_open_items))
        if not profiles: raise ValidationError("No eligible agent is available within capacity.")
        if self.strategy=="AI_FIRST": profiles=profiles.sorted(key=lambda row:(row.agent_type!="AI",workloads[row.id],row.id))
        if self.strategy in ("LOAD_BALANCED","SKILL_BASED","HUMAN_ONLY","AI_FIRST"): selected=min(profiles,key=lambda row:(workloads[row.id],row.id)) if self.strategy!="AI_FIRST" else profiles[0]
        else: selected=profiles[self.next_sequence%len(profiles)]; self.next_sequence+=1
        lead.write({"assigned_agent_profile_id":selected.id,"user_id":selected.user_id.id})
        self.env["codestra.activity.timeline"].sudo().create({"event_type":"ASSIGNMENT_CHANGE","actor_type":"SYSTEM","actor_id":"lead-distribution","action":f"assignment.{self.strategy.lower()}","campaign_id":self.campaign_id.id,"lead_id":lead.id,"visibility":"INTERNAL","source_system":"odoo","correlation_id":lead.correlation_id or str(uuid.uuid4()),"safe_detail":{"agent_uuid":selected.agent_uuid,"strategy":self.strategy}})
        return selected


class CommandCenterSnapshot(models.Model):
    _name="codestra.command.center.snapshot"; _description="Scoped Campaign Command Center"; _order="generated_at desc"
    campaign_id=fields.Many2one("call.center.campaign",required=True,ondelete="cascade",index=True); business_unit_id=fields.Many2one(related="campaign_id.business_unit_id",store=True,index=True)
    generated_at=fields.Datetime(default=fields.Datetime.now,required=True,readonly=True,index=True)
    human_agents_active=fields.Integer(readonly=True); ai_agents_active=fields.Integer(readonly=True); new_leads=fields.Integer(readonly=True); open_leads=fields.Integer(readonly=True); unassigned_leads=fields.Integer(readonly=True)
    callbacks_due=fields.Integer(readonly=True); callbacks_overdue=fields.Integer(readonly=True); appointments_today=fields.Integer(readonly=True); appointment_no_shows=fields.Integer(readonly=True)
    overdue_followups=fields.Integer(readonly=True); sla_violations=fields.Integer(readonly=True); communications_waiting=fields.Integer(readonly=True); automation_failures=fields.Integer(readonly=True); metrics=fields.Json(default=dict,readonly=True)

    @api.model
    def refresh(self):
        now=fields.Datetime.now(); start=fields.Datetime.to_datetime(fields.Date.context_today(self)); end=start+timedelta(days=1)
        for workflow in self.env["codestra.campaign.workflow"].search([("campaign_id","!=",False)]):
            campaign=workflow.campaign_id; leads=self.env["crm.lead"].search([("call_center_campaign_id","=",campaign.id),("active","in",(True,False))]); profiles=self.env["codestra.agent.profile"].search([("campaign_ids","in",campaign.id),("active","=",True)]); appointments=self.env["codestra.crm.appointment"].search([("campaign_id","=",campaign.id),("scheduled_start",">=",start),("scheduled_start","<",end)])
            values={"campaign_id":campaign.id,"human_agents_active":len(profiles.filtered(lambda row:row.agent_type=="HUMAN")),"ai_agents_active":len(profiles.filtered(lambda row:row.agent_type=="AI")),"new_leads":len(leads.filtered(lambda row:not row.codestra_previous_status_id)),"open_leads":len(leads.filtered(lambda row:not row.codestra_current_status_id.terminal)),"unassigned_leads":len(leads.filtered(lambda row:not row.assigned_agent_profile_id)),"callbacks_due":len(leads.filtered(lambda row:row.callback_at and row.callback_at<=now)),"callbacks_overdue":len(leads.filtered(lambda row:row.callback_at and row.callback_at<now)),"appointments_today":len(appointments),"appointment_no_shows":len(appointments.filtered(lambda row:row.status in ("CUSTOMER_NO_SHOW","AGENT_NO_SHOW"))),"overdue_followups":len(leads.filtered(lambda row:row.next_action_at and row.next_action_at<now)),"sla_violations":len(leads.filtered(lambda row:row.next_action_at and row.next_action_at<now)),"communications_waiting":self.env["codestra.campaign.communication"].search_count([("campaign_id","=",campaign.id),("status","=","REPLIED")]),"automation_failures":self.env["codestra.crm.outbox"].search_count([("campaign_id","=",campaign.id),("state","=","DEAD_LETTER")])}
            values["metrics"]={key:value for key,value in values.items() if key!="campaign_id"}; self.create(values)
        return True


class CRMLeadClient360(models.Model):
    _inherit="crm.lead"
    codestra_timeline_ids=fields.One2many("codestra.activity.timeline","lead_id",readonly=True); codestra_document_ids=fields.One2many("codestra.campaign.document","lead_id",readonly=True)
    codestra_communication_ids=fields.One2many("codestra.campaign.communication","lead_id",readonly=True); codestra_queue_item_ids=fields.One2many("codestra.work.queue.item","lead_id",readonly=True)
