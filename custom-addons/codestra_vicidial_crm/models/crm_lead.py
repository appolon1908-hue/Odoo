import uuid

from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.modules.registry import Registry

from .phone import normalize_phone
from .middleware_client import OriginateOutcomeUnknown, OriginateRejected, validate_originate_result


AUTHORITATIVE_TERMINAL_STATES = frozenset(
    {"completed", "failed", "missed", "cancelled", "rejected", "transferred"}
)


def dispatch_reserved_call(database, call_id):
    """Dispatch a committed reservation in an independent transaction."""
    with Registry(database).cursor() as cursor:
        dispatch_env = api.Environment(cursor, SUPERUSER_ID, {})
        dispatch_env["codestra.vicidial.call"].browse(
            call_id
        )._dispatch_click_to_call()
        cursor.commit()


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
        self.env.cr.execute(
            "SELECT id FROM codestra_vicidial_agent WHERE id = %s FOR UPDATE",
            (agent.id,),
        )
        pending = Call.search(
            [
                ("agent_id", "=", agent.id),
                ("tenant_id", "=", agent.tenant_id),
                (
                    "state",
                    "in",
                    [
                        "new", "initiating", "ringing", "offered", "answering",
                        "connected", "held", "transferring", "ending",
                    ],
                ),
            ],
            order="create_date desc",
            limit=1,
        )
        if pending and pending.status not in ("requesting", "outcome_unknown"):
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
                    "original_number": destination,
                    "normalized_number": destination,
                    "caller_id": outbound_caller_id,
                    "start_at": fields.Datetime.now(),
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
        payload = pending.originate_payload if pending else {
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
        if not pending:
            call.originate_payload = payload
        database = self.env.cr.dbname
        call_id = call.id

        def dispatch_after_commit():
            dispatch_reserved_call(database, call_id)

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
    originate_result_class = fields.Selection(
        [("accepted", "Accepted"), ("rejected", "Rejected"), ("unknown", "Unknown")],
        copy=False,
    )
    originate_result_reason = fields.Char(copy=False)

    def _notify_originate_result(self, outcome, reason):
        if self.agent_id.odoo_user_id:
            self.env["bus.bus"]._sendone(
                self.agent_id.odoo_user_id.partner_id,
                "codestra.call.result",
                {
                    "correlation_id": self.correlation_id,
                    "outcome": outcome,
                    "reason": reason,
                },
            )

    def _lock_pending_dispatch(self):
        """Recheck the persisted reservation under the same row lock as writes."""
        self.ensure_one()
        self.flush_recordset(["state", "status", "call_id"])
        self.env.cr.execute(
            "SELECT id FROM codestra_vicidial_call WHERE id = %s FOR UPDATE",
            [self.id],
        )
        self.invalidate_recordset(["state", "status", "call_id"])
        # Authoritative lifecycle progress, and an already accepted dispatch,
        # take precedence over a late response from a duplicate dispatcher.
        return self.state == "initiating" and self.status in (
            "requesting", "outcome_unknown",
        )

    def _record_dispatch_failure(self, classification, reason):
        if not self._lock_pending_dispatch():
            return
        safe_reason = " ".join((reason or "Call dispatch failed.").split())[:240]
        values = {
            "originate_result_class": classification,
            "originate_result_reason": safe_reason,
        }
        if classification == "rejected":
            values.update(
                {"state": "failed", "status": "rejected", "ended_at": fields.Datetime.now()}
            )
        else:
            values["status"] = "outcome_unknown"
        self.write(values)
        self._notify_originate_result(classification, safe_reason)

    def _dispatch_click_to_call(self):
        self.ensure_one()
        if self.state not in ("initiating",) or self.status not in (
            "requesting",
            "outcome_unknown",
        ):
            return
        try:
            result = self.env["codestra.telephony.middleware.client"].originate_call(
                self.correlation_id,
                self.idempotency_key,
                self.originate_payload,
            )
            result = validate_originate_result(result)
        except OriginateRejected as exc:
            self._record_dispatch_failure("rejected", str(exc))
            return
        except OriginateOutcomeUnknown as exc:
            self._record_dispatch_failure("unknown", str(exc))
            return
        except Exception:
            # A request may have crossed the process boundary before an unexpected
            # client failure. Keep it reconcilable and never expose exception detail.
            self._record_dispatch_failure(
                "unknown",
                "Unexpected dispatch failure with an unknown call outcome; "
                "reconcile this call before retrying.",
            )
            return
        if not self._lock_pending_dispatch():
            return
        attempting = result.get("dialing") == "attempting"
        unknown = result.get("dialing") == "unknown"
        values = {
            "status": result.get("dialing") or "invalid_response",
            "originate_result_class": "accepted" if attempting else "unknown" if unknown else "rejected",
            "originate_result_reason": " ".join(
                (result.get("reason") or "Call dispatch result received.").split()
            )[:240],
        }
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
        if not attempting:
            self._notify_originate_result(
                "unknown" if unknown else "rejected",
                values["originate_result_reason"],
            )
