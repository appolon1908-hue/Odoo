import re
import uuid

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CodestraAiAssistantDraft(models.Model):
    _name = "codestra.ai.assistant.draft"
    _description = "Codestra AI Assistant Draft"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"
    _check_company_auto = True

    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    request_type = fields.Selection(
        [
            ("interaction_summary", "Interaction Summary"),
            ("knowledge_suggestion", "Knowledge Suggestion"),
            ("response_draft", "Response Draft"),
        ],
        required=True,
        index=True,
        tracking=True,
    )
    call_id = fields.Many2one(
        "codestra.vicidial.call",
        string="Controlled Call Reference",
        ondelete="restrict",
        index=True,
    )
    partner_id = fields.Many2one("res.partner", ondelete="restrict", index=True)
    lead_id = fields.Many2one("crm.lead", ondelete="restrict", check_company=True, index=True)
    correlation_id = fields.Char(
        required=True,
        copy=False,
        default=lambda self: str(uuid.uuid4()),
        index=True,
    )
    idempotency_key = fields.Char(required=True, copy=False, index=True)
    input_reference = fields.Char(
        required=True,
        help="Controlled evidence reference only; raw provider prompts and secrets are not stored.",
    )
    prompt_hash = fields.Char(required=True, copy=False, index=True)
    provider = fields.Char(readonly=True, copy=False)
    model_name = fields.Char(readonly=True, copy=False)
    response_hash = fields.Char(readonly=True, copy=False, index=True)
    output_text = fields.Text(readonly=True, copy=False)
    output_classification = fields.Selection(
        [
            ("informational", "Informational"),
            ("needs_review", "Needs Review"),
            ("sensitive", "Sensitive"),
        ],
        readonly=True,
        copy=False,
    )
    state = fields.Selection(
        [
            ("requested", "Requested"),
            ("generated", "Generated"),
            ("approved", "Approved Draft"),
            ("rejected", "Rejected"),
            ("expired", "Expired"),
        ],
        required=True,
        default="requested",
        index=True,
        tracking=True,
        copy=False,
    )
    requested_by_id = fields.Many2one(
        "res.users",
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
        copy=False,
    )
    generated_at = fields.Datetime(readonly=True, copy=False)
    reviewed_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    reviewed_at = fields.Datetime(readonly=True, copy=False)
    review_note = fields.Text(tracking=True)
    expires_at = fields.Datetime(index=True, copy=False)

    _idempotency_unique = models.Constraint(
        "unique(idempotency_key)",
        "An AI assistant idempotency key may be recorded once.",
    )

    @api.model_create_multi
    def create(self, values_list):
        protected = {
            "provider",
            "model_name",
            "response_hash",
            "output_text",
            "output_classification",
            "generated_at",
            "reviewed_by_id",
            "reviewed_at",
        }
        for values in values_list:
            if protected.intersection(values):
                raise ValidationError(_("Generated or review fields cannot be supplied when requesting a draft."))
            values["state"] = "requested"
            values["requested_by_id"] = self.env.user.id
        return super().create(values_list)

    @api.constrains("prompt_hash", "response_hash")
    def _check_hashes(self):
        for record in self:
            if not SHA256_RE.fullmatch((record.prompt_hash or "").lower()):
                raise ValidationError(_("Prompt hash must be a lowercase SHA-256 digest."))
            if record.response_hash and not SHA256_RE.fullmatch(record.response_hash.lower()):
                raise ValidationError(_("Response hash must be a lowercase SHA-256 digest."))

    @api.constrains("output_text")
    def _check_output_length(self):
        for record in self:
            if len(record.output_text or "") > 20000:
                raise ValidationError(_("AI assistant output exceeds the reviewed storage limit."))

    def write(self, values):
        generated_fields = {
            "provider",
            "model_name",
            "response_hash",
            "output_text",
            "output_classification",
            "generated_at",
        }
        if generated_fields.intersection(values) and not self.env.context.get("assistant_generation_write"):
            raise AccessError(_("Generated fields may be written only through the authorized generation recorder."))
        review_fields = {"reviewed_by_id", "reviewed_at"}
        if review_fields.intersection(values) and not self.env.context.get("assistant_review_write"):
            raise AccessError(_("Review evidence may be written only through a review action."))
        return super().write(values)

    def record_generation(
        self,
        *,
        provider,
        model_name,
        response_hash,
        output_text,
        classification="needs_review",
    ):
        if not (
            self.env.user.has_group("codestra_ai_agent_assistant.group_codestra_ai_service")
            or self.env.user.has_group("call_center_core.group_call_center_admin")
        ):
            raise AccessError(_("Only the AI service role may record generated output."))
        if classification not in {"informational", "needs_review", "sensitive"}:
            raise ValidationError(_("Unsupported AI output classification."))
        for record in self:
            if record.state != "requested":
                raise UserError(_("Only requested drafts can accept generated output."))
            record.with_context(assistant_generation_write=True).write(
                {
                    "provider": (provider or "")[:128],
                    "model_name": (model_name or "")[:128],
                    "response_hash": (response_hash or "").lower(),
                    "output_text": output_text or "",
                    "output_classification": classification,
                    "generated_at": fields.Datetime.now(),
                    "state": "generated",
                }
            )
        return True

    def _require_reviewer(self):
        if not (
            self.env.user.has_group("codestra_ai_agent_assistant.group_codestra_ai_reviewer")
            or self.env.user.has_group("call_center_core.group_call_center_admin")
        ):
            raise AccessError(_("A designated AI reviewer is required."))

    def action_approve(self):
        self._require_reviewer()
        for record in self:
            if record.state != "generated":
                raise UserError(_("Only generated drafts can be approved."))
            if record.requested_by_id == self.env.user:
                raise ValidationError(_("The requester cannot approve the same AI draft."))
            record.with_context(assistant_review_write=True).write(
                {
                    "state": "approved",
                    "reviewed_by_id": self.env.user.id,
                    "reviewed_at": fields.Datetime.now(),
                }
            )
        return True

    def action_reject(self):
        self._require_reviewer()
        for record in self:
            if record.state != "generated":
                raise UserError(_("Only generated drafts can be rejected."))
            if not (record.review_note or "").strip():
                raise ValidationError(_("A review note is required when rejecting a draft."))
            record.with_context(assistant_review_write=True).write(
                {
                    "state": "rejected",
                    "reviewed_by_id": self.env.user.id,
                    "reviewed_at": fields.Datetime.now(),
                }
            )
        return True

    def action_expire(self):
        for record in self:
            if record.state not in {"generated", "approved"}:
                raise UserError(_("Only generated or approved drafts can expire."))
            record.state = "expired"
        return True
