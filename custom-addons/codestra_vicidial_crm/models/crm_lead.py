import uuid

from odoo import SUPERUSER_ID, api, fields, models, registry
from odoo.exceptions import UserError, ValidationError

from .phone import normalize_phone


class CrmLead(models.Model):
    _inherit = "crm.lead"

    x_vicidial_lead_id = fields.Integer(index=True)
    x_vicidial_campaign_id = fields.Char(index=True)
    x_vicidial_list_id = fields.Integer(index=True)
    x_vicidial_status = fields.Char()
    x_vicidial_vendor_lead_code = fields.Char(index=True)
    x_phone_raw = fields.Char()
    x_phone_e164 = fields.Char(compute="_compute_codestra_phone", store=True, index=True)
    x_last_call_uniqueid = fields.Char(index=True)
    x_last_call_datetime = fields.Datetime()
    x_last_call_disposition = fields.Char()
    x_last_agent = fields.Char()
    x_call_count = fields.Integer(default=0)
    x_answered_call_count = fields.Integer(default=0)
    x_sync_status = fields.Selection(
        [("pending", "Pending"), ("clean", "Clean"), ("error", "Error")],
        default="pending",
        index=True,
    )
    x_sync_error = fields.Text()
    x_assigned_setter_id = fields.Many2one("res.users", index=True)
    x_assigned_closer_id = fields.Many2one("res.users", index=True)
    x_assigned_supervisor_id = fields.Many2one("res.users", index=True)
    x_current_owner_role = fields.Selection([("setter", "Setter"), ("closer", "Closer"), ("supervisor", "Supervisor")])
    x_transfer_eligibility = fields.Selection(
        [("eligible", "Eligible"), ("blocked", "Blocked"), ("pending", "Pending")],
        default="pending",
    )
    x_timezone = fields.Char()
    x_preferred_language = fields.Selection([("en", "English"), ("es", "Spanish"), ("fr", "French"), ("ar", "Arabic")])
    x_contact_consent = fields.Boolean()
    x_do_not_call = fields.Boolean(index=True)
    x_consent_source = fields.Char()
    x_consent_timestamp = fields.Datetime()
    x_call_answered_at = fields.Datetime()
    x_total_talk_seconds = fields.Integer(default=0)
    x_last_call_quality_score = fields.Float()
    x_ai_lead_score = fields.Float()
    x_ai_confidence = fields.Float()
    x_customer_sentiment = fields.Selection(
        [("positive", "Positive"), ("neutral", "Neutral"), ("negative", "Negative")]
    )
    x_primary_objection = fields.Char()
    x_required_disclosure_status = fields.Selection(
        [("pending", "Pending"), ("complete", "Complete"), ("failed", "Failed")],
        default="pending",
    )
    x_qualification_status = fields.Selection(
        [("new", "New"), ("qualified", "Qualified"), ("unqualified", "Unqualified")],
        default="new",
    )
    x_ai_summary = fields.Text()
    x_last_sync_at = fields.Datetime()
    x_sync_version = fields.Integer(default=1)
    x_source_system = fields.Char(default="vicidial")
    vicidial_lead_id = fields.Char(index=True)
    vicidial_list_id = fields.Char(index=True)
    vicidial_campaign_id = fields.Char(index=True)
    assigned_vicidial_agent_id = fields.Many2one("codestra.vicidial.agent")
    latest_call_id = fields.Many2one("codestra.vicidial.call")
    call_count = fields.Integer(compute="_compute_call_count")
    latest_disposition_id = fields.Many2one("codestra.vicidial.disposition")
    latest_call_at = fields.Datetime()
    callback_at = fields.Datetime()
    do_not_call = fields.Boolean()
    preferred_language = fields.Char()
    integration_state = fields.Selection([("new", "New"), ("synced", "Synced"), ("error", "Error")], default="new")
    external_source = fields.Char()
    correlation_id = fields.Char(index=True)

    @api.model
    def normalize_codestra_phone(self, value):
        return normalize_phone(value)

    @api.depends("phone")
    def _compute_codestra_phone(self):
        for record in self:
            try:
                record.x_phone_e164 = normalize_phone(record.phone)
            except ValidationError:
                record.x_phone_e164 = False

    def _compute_call_count(self):
        calls = self.env["codestra.vicidial.call"].read_group(
            [("crm_lead_id", "in", self.ids)], ["crm_lead_id"], ["crm_lead_id"]
        )
        counts = {item["crm_lead_id"][0]: item["crm_lead_id_count"] for item in calls if item.get("crm_lead_id")}
        for record in self:
            record.call_count = counts.get(record.id, 0)

    def action_click_to_call(self):
        """Request a governed outbound call through Codestra Middleware."""
        self.ensure_one()
        agent = self.env["codestra.vicidial.agent"].search(
            [("odoo_user_id", "=", self.env.uid), ("active", "=", True)], limit=1
        )
        if not agent:
            raise UserError(
                "Your account is not linked to an active VICIdial agent profile."
            )
        if agent.status not in ("active", "ready"):
            status_label = dict(agent._fields["status"].selection).get(
                agent.status, agent.status
            )
            raise UserError(
                "You must be Ready before placing a call (current status: %s)."
                % status_label
            )
        if (
            not self.env.user.codestra_tenant_id
            or self.env.user.codestra_tenant_id != agent.tenant_id
            or not self.env.user.keycloak_subject
        ):
            raise UserError(
                "Your browser identity is not bound to this VICIdial tenant."
            )
        if self.x_do_not_call or self.do_not_call:
            raise UserError("This contact is on the do-not-call list.")

        destination = self.x_phone_e164 or self.normalize_codestra_phone(self.phone)
        if not destination or not destination.startswith("+"):
            raise UserError("Add a valid E.164 phone number before placing a call.")
        if not self.business_unit_id or not self.business_unit_id.code:
            raise UserError("This lead has no business unit assigned.")

        campaigns_by_code = {item.campaign_id: item for item in agent.campaign_ids}
        campaign_code = self.x_vicidial_campaign_id
        if not campaign_code and len(campaigns_by_code) == 1:
            campaign_code = next(iter(campaigns_by_code))
        if not campaign_code or campaign_code not in campaigns_by_code:
            raise UserError("You are not assigned to the campaign for this lead.")

        params = self.env["ir.config_parameter"].sudo()
        destination_class = params.get_param(
            "codestra.telephony.destination_class"
        )
        destination_country = params.get_param(
            "codestra.telephony.destination_country"
        )
        outbound_caller_id = params.get_param(
            "codestra.telephony.approved_outbound_caller_id"
        )
        if (
            not destination_class
            or not destination_country
            or not outbound_caller_id
        ):
            raise UserError(
                "Click-to-call compliance is not configured. Set the approved "
                "destination class, country, and outbound caller ID system parameters."
            )

        campaign = campaigns_by_code[campaign_code]
        Call = self.env["codestra.vicidial.call"].sudo()
        pending = Call.search(
            [
                ("agent_id", "=", agent.id),
                ("tenant_id", "=", agent.tenant_id),
                (
                    "state",
                    "in",
                    ["initiating", "ringing", "offered", "answering", "connected"],
                ),
            ],
            order="create_date desc",
            limit=1,
        )
        if pending and pending.status != "outcome_unknown":
            raise UserError(
                "You already have an active call request. Wait for its outcome."
            )

        if pending and (
            pending.crm_lead_id != self
            or pending.campaign_id != campaign
            or pending.destination != destination
        ):
            raise UserError(
                "Your previous call has an unknown outcome. Reconcile it from its "
                "original lead before placing another call."
            )

        if pending:
            call = pending
            correlation_id = pending.correlation_id
            idempotency_key = pending.idempotency_key
        else:
            correlation_id = str(uuid.uuid4())
            idempotency_key = correlation_id
            call = Call.create(
                {
                    "name": "Click-to-call %s" % correlation_id,
                    "crm_lead_id": self.id,
                    "lead_id": self.id,
                    "agent_id": agent.id,
                    "campaign_id": campaign.id,
                    "direction": "outbound",
                    "destination": destination,
                    "caller_id": outbound_caller_id,
                    "state": "initiating",
                    "status": "requesting",
                    "idempotency_key": idempotency_key,
                    "correlation_id": correlation_id,
                    "campaign_code": campaign_code,
                    "business_unit_id": self.business_unit_id.code,
                    "tenant_id": agent.tenant_id,
                    "keycloak_subject": self.env.user.keycloak_subject,
                    "vicidial_user": agent.vicidial_user,
                    "extension": agent.phone_login,
                }
            )
        payload = {
                "employee_id": agent.employee_code or agent.vicidial_user,
                "campaign": campaign_code,
                "business_unit": self.business_unit_id.code,
                "destination": destination,
                "destination_class": destination_class,
                "destination_country": destination_country,
                "destination_timezone": self.x_timezone or self.env.user.tz or "UTC",
                "caller_id": outbound_caller_id,
                "lead_model": "crm.lead",
                "lead_id": self.id,
                "recording_requested": False,
            }
        call.originate_payload = payload
        database = self.env.cr.dbname
        call_id = call.id

        def dispatch_after_commit():
            with registry(database).cursor() as cursor:
                dispatch_env = api.Environment(cursor, SUPERUSER_ID, {})
                dispatch_env["codestra.vicidial.call"].browse(
                    call_id
                )._dispatch_click_to_call()
                cursor.commit()

        # The callback only runs after the reservation is committed. If this worker
        # exits first, another click finds the same key and schedules it again.
        self.env.cr.postcommit.add(dispatch_after_commit)
        message = "Call request queued with a durable duplicate-prevention key."
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Click-to-call",
                "message": message,
                "sticky": False,
                "type": "success",
            },
        }


class ClickToCallDispatch(models.Model):
    _inherit = "codestra.vicidial.call"

    originate_payload = fields.Json(copy=False)

    def _dispatch_click_to_call(self):
        self.ensure_one()
        if self.state not in ("initiating",) or self.status not in (
            "requesting",
            "outcome_unknown",
        ):
            return
        result = self.env["codestra.telephony.middleware.client"].originate_call(
            self.correlation_id,
            self.idempotency_key,
            self.originate_payload,
        )
        attempting = result.get("dialing") == "attempting"
        unknown = result.get("dialing") == "unknown"
        values = {"status": result.get("dialing") or "invalid_response"}
        if result.get("call_id"):
            values.update(
                {
                    "call_id": result["call_id"],
                    "external_call_id": result["call_id"],
                }
            )
        if unknown:
            values["status"] = "outcome_unknown"
        elif not attempting:
            values.update({"state": "failed", "ended_at": fields.Datetime.now()})
        self.write(values)
