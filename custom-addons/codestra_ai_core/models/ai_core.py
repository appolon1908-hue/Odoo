from odoo import api, fields, models
from odoo.exceptions import ValidationError

TASK_CODES = [
    "lead_prequalification", "lead_fit_scoring", "urgency_classification",
    "campaign_recommendation", "language_detection", "call_transcription",
    "call_summary", "sentiment_analysis", "objection_detection",
    "disclosure_detection", "forbidden_phrase_detection", "compliance_review",
    "qa_review", "next_best_action", "retention_risk", "upsell_recommendation",
    "failed_payment_recommendation", "supervisor_escalation",
]


class AITaskType(models.Model):
    _name = "codestra.ai.task.type"
    _description = "AI Task Type"
    _inherit = "call.center.business.unit.mixin"

    name = fields.Char(required=True)
    code = fields.Selection([(x, x.replace("_", " ").title()) for x in TASK_CODES],
                            required=True, index=True)
    campaign_ids = fields.Many2many("call.center.campaign")
    input_schema = fields.Json(required=True)
    output_schema = fields.Json(required=True)
    provider_ids = fields.Many2many("codestra.ai.provider")
    mode = fields.Selection([("realtime", "Real-time"), ("async", "Asynchronous")],
                            required=True, default="async")
    timeout_seconds = fields.Integer(default=30, required=True)
    confidence_threshold = fields.Float(default=.7, required=True)
    human_review_required = fields.Boolean(default=True)
    retention_days = fields.Integer(default=30)
    feature_flag = fields.Char(required=True)
    active = fields.Boolean(default=False)

    _code_unit_unique = models.Constraint(
        "unique(code, business_unit_id)", "Task codes must be unique per business unit.")

    @api.constrains("confidence_threshold")
    def _check_confidence(self):
        if any(x.confidence_threshold < 0 or x.confidence_threshold > 1 for x in self):
            raise ValidationError("Confidence must be between zero and one.")


class AIProvider(models.Model):
    _name = "codestra.ai.provider"
    _description = "AI Provider Reference"
    _inherit = "call.center.business.unit.mixin"

    name = fields.Char(required=True)
    provider_class = fields.Selection([
        ("stt", "Speech to Text"), ("llm", "Language Model"),
        ("sentiment", "Sentiment"), ("compliance", "Compliance"),
        ("embedding", "Embedding"), ("self_hosted_llm", "Self-hosted LLM"),
        ("self_hosted_stt", "Self-hosted STT"), ("rules", "Rules Engine"),
    ], required=True)
    credential_reference = fields.Char()
    region = fields.Char()
    active = fields.Boolean(default=False)

    @api.constrains("credential_reference")
    def _no_inline_secret(self):
        for row in self:
            value = row.credential_reference or ""
            if value and not value.startswith(("vault:", "secret:", "ref:")):
                raise ValidationError("Only opaque credential references are allowed.")


class AIAudit(models.Model):
    _name = "codestra.ai.audit"
    _description = "Immutable AI Audit Reference"
    _inherit = "call.center.business.unit.mixin"

    task_type_id = fields.Many2one("codestra.ai.task.type", required=True)
    campaign_id = fields.Many2one("call.center.campaign", required=True)
    entity_reference = fields.Char(required=True)
    correlation_id = fields.Char(required=True, index=True)
    idempotency_hash = fields.Char(required=True, index=True)
    provider_id = fields.Many2one("codestra.ai.provider")
    prompt_version = fields.Char()
    status = fields.Selection([("requested", "Requested"), ("quarantined", "Quarantined"),
                               ("reviewed", "Reviewed"), ("failed", "Failed")],
                              default="requested", required=True)
    safe_result = fields.Json()

    _idempotency_unique = models.Constraint(
        "unique(idempotency_hash)", "AI idempotency hashes must be unique.")


class AIPromptTemplate(models.Model):
    _name = "codestra.ai.prompt.template"
    _description = "Versioned AI Prompt"
    _inherit = "call.center.business.unit.mixin"

    name = fields.Char(required=True)
    task_type_id = fields.Many2one("codestra.ai.task.type", required=True)
    campaign_id = fields.Many2one("call.center.campaign", required=True)
    language = fields.Char(default="en", required=True)
    version = fields.Char(required=True)
    state = fields.Selection([
        ("draft", "Draft"), ("testing", "Testing"),
        ("compliance_review", "Compliance Review"), ("approved", "Approved"),
        ("published", "Published"), ("superseded", "Superseded"),
        ("archived", "Archived")], default="draft", required=True)
    system_instructions = fields.Text(required=True)
    input_schema = fields.Json(required=True)
    output_schema = fields.Json(required=True)
    effective_at = fields.Datetime()
    expires_at = fields.Datetime()
