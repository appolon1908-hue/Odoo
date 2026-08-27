import hashlib
import json

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


class CodestraDispositionCertification(models.Model):
    _inherit = "codestra.disposition"

    target_stage_id = fields.Many2one("crm.stage", ondelete="restrict")
    activity_policy = fields.Selection(
        [("none", "None"), ("callback", "Callback"),
         ("appointment", "Appointment"), ("close", "Close Open Activities")],
        required=True, default="none",
    )
    dnc_policy = fields.Selection(
        [("preserve", "Preserve"), ("permanent", "Permanent Suppression")],
        required=True, default="preserve",
    )
    note_policy = fields.Selection(
        [("required", "Required Safe Note"), ("optional", "Optional Safe Note")],
        required=True, default="required",
    )
    idempotency_namespace = fields.Char(required=True, default="vicidial-event:v1")


class CrmLeadCertificationState(models.Model):
    _inherit = "crm.lead"

    x_test_syn_lead_ref = fields.Char(copy=False, index=True)
    x_vicidial_last_event_at = fields.Datetime(copy=False, index=True)
    x_vicidial_last_event_id = fields.Char(copy=False, index=True)
    x_vicidial_retry_count = fields.Integer(default=0, copy=False)

    _test_syn_lead_ref_unique = models.Constraint(
        "unique(x_test_syn_lead_ref)", "TEST_SYN lead references must be unique."
    )


class CodestraCrmMutation(models.Model):
    _name = "codestra.crm.mutation"
    _description = "Immutable TEST_SYN CRM Mutation Receipt"
    _order = "id"

    event_id = fields.Char(required=True, readonly=True, index=True)
    idempotency_key = fields.Char(required=True, readonly=True, index=True)
    payload_hash = fields.Char(required=True, readonly=True, size=64)
    occurred_at = fields.Datetime(required=True, readonly=True)
    status_code = fields.Char(required=True, readonly=True)
    lead_id = fields.Many2one("crm.lead", required=True, readonly=True, ondelete="restrict")
    result = fields.Selection(
        [("applied", "Applied"), ("stale", "Stale")], required=True, readonly=True
    )

    _event_unique = models.Constraint("unique(event_id)", "Event IDs must be unique.")
    _key_unique = models.Constraint(
        "unique(idempotency_key)", "Mutation idempotency keys must be unique."
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("_test_syn_certification"):
            raise AccessError("Mutation receipts require the TEST_SYN certification capability.")
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError("Mutation receipts are immutable.")

    def unlink(self):
        raise AccessError("Mutation receipts are immutable.")

    @api.model
    def apply_test_syn(self, payload):
        """Apply one synthetic event. This is deliberately not an HTTP endpoint."""
        if not self.env.context.get("_test_syn_certification"):
            raise AccessError("TEST_SYN certification capability is required.")
        required = {"event_id", "idempotency_key", "occurred_at", "status", "lead_ref", "note"}
        missing = sorted(required - set(payload))
        if missing:
            raise ValidationError("Missing mutation fields: %s" % ", ".join(missing))
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        payload_hash = hashlib.sha256(canonical.encode()).hexdigest()
        existing = self.search([("event_id", "=", payload["event_id"])], limit=1)
        if existing:
            if existing.payload_hash != payload_hash or existing.idempotency_key != payload["idempotency_key"]:
                raise ValidationError("Conflicting retry for an existing event ID.")
            return {"result": "duplicate", "lead_id": existing.lead_id.id}
        key_match = self.search([("idempotency_key", "=", payload["idempotency_key"])], limit=1)
        if key_match:
            raise ValidationError("Conflicting retry for an existing idempotency key.")

        mapping = self.env.ref("codestra_odoo_certification.mapping_test_syn")
        if mapping.active or mapping.production_eligible or mapping.desired_state != "inactive":
            raise ValidationError("TEST_SYN mapping must remain disabled.")
        status = str(payload["status"]).strip().upper()
        disposition_candidates = self.env["codestra.disposition"].search([
            ("campaign_id", "=", mapping.campaign_id.id),
            ("active", "=", True),
            "|",
            ("code", "=", status),
            ("vicidial_status_code", "=", status),
        ], limit=2)
        if not disposition_candidates:
            raise ValidationError("No deterministic TEST_SYN disposition mapping.")
        if len(disposition_candidates) != 1:
            raise ValidationError("Ambiguous TEST_SYN disposition mapping.")
        disposition = disposition_candidates
        canonical_status = disposition.code
        physical_status = disposition.vicidial_status_code
        if disposition.note_policy == "required" and not str(payload["note"]).strip():
            raise ValidationError("A safe note is required for this disposition.")

        lead = self.env["crm.lead"].search([
            ("x_test_syn_lead_ref", "=", payload["lead_ref"]),
            ("company_id", "=", mapping.company_id.id),
        ], limit=1)
        if not lead:
            lead = self.env["crm.lead"].create({
                "name": "TEST_SYN fictional non-dialable lead",
                "type": "opportunity",
                "x_test_syn_lead_ref": payload["lead_ref"],
                "company_id": mapping.company_id.id,
                "team_id": mapping.crm_team_id.id,
                "business_unit_id": mapping.business_unit_id.id,
                "call_center_campaign_id": mapping.campaign_id.id,
                "is_codestra_call_center_lead": True,
                "phone": False,
                "x_vicidial_campaign_id": "TEST_SYN",
                "x_source_system": "vicidial",
            })
        occurred_at = fields.Datetime.to_datetime(payload["occurred_at"])
        result = "applied"
        if lead.x_vicidial_last_event_at and occurred_at <= lead.x_vicidial_last_event_at:
            result = "stale"
        else:
            values = {
                "x_vicidial_status": canonical_status,
                "x_last_call_disposition": canonical_status,
                "latest_disposition_id": self.env["codestra.vicidial.disposition"].search(
                    [("code", "=", physical_status)], limit=1
                ).id or False,
                "x_vicidial_last_event_at": occurred_at,
                "x_vicidial_last_event_id": payload["event_id"],
                "x_vicidial_retry_count": min(
                    int(payload.get("retry_count", 0)), disposition.maximum_retries
                ),
            }
            permanently_suppressed = lead.x_do_not_call or lead.do_not_call
            if disposition.target_stage_id and (
                not permanently_suppressed or disposition.dnc_policy == "permanent"
            ):
                values["stage_id"] = disposition.target_stage_id.id
            if disposition.dnc_policy == "permanent":
                values.update({"x_do_not_call": True, "do_not_call": True, "x_contact_consent": False})
            lead.write(values)
            open_activities = lead.activity_ids
            if disposition.activity_policy == "close":
                open_activities.action_done()
            elif (
                disposition.activity_policy in ("callback", "appointment")
                and not permanently_suppressed
            ):
                summary = "TEST_SYN callback" if disposition.activity_policy == "callback" else "TEST_SYN appointment"
                existing_activity = open_activities.filtered(lambda activity: activity.summary == summary)
                deadline = fields.Date.to_date(payload.get("activity_date") or fields.Date.today())
                if existing_activity:
                    existing_activity.write({"date_deadline": deadline, "note": "Synthetic certification activity"})
                else:
                    lead.activity_schedule(
                        "mail.mail_activity_data_todo", date_deadline=deadline,
                        summary=summary, note="Synthetic certification activity",
                    )
            lead.message_post(
                body="VICIdial %s (%s): %s"
                % (physical_status, canonical_status, str(payload["note"])[:160])
            )
        receipt = self.create({
            "event_id": payload["event_id"], "idempotency_key": payload["idempotency_key"],
            "payload_hash": payload_hash, "occurred_at": occurred_at,
            "status_code": canonical_status, "lead_id": lead.id, "result": result,
        })
        return {"result": receipt.result, "lead_id": lead.id}
