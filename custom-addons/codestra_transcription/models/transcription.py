from odoo import api, fields, models
from odoo.exceptions import ValidationError


class TranscriptScope(models.AbstractModel):
    _name = "codestra.call.transcript.scope.mixin"
    _description = "Transcript Scope"

    business_unit_id = fields.Many2one("call.center.business.unit", required=True, index=True)
    campaign_id = fields.Many2one("call.center.campaign", required=True, index=True)
    call_reference = fields.Char(required=True, index=True)
    correlation_id = fields.Char(required=True, index=True)
    security_classification = fields.Selection([
        ("restricted", "Restricted"), ("confidential", "Confidential"),
        ("legal_hold", "Legal Hold"),
    ], default="restricted", required=True)
    retention_until = fields.Datetime(required=True)
    legal_hold = fields.Boolean(default=False)
    test_only = fields.Boolean(default=True, required=True)
    active = fields.Boolean(default=False)

    @api.constrains("business_unit_id", "campaign_id")
    def _check_scope(self):
        for row in self:
            if row.campaign_id.business_unit_id != row.business_unit_id:
                raise ValidationError("Transcript scope cannot cross business units.")


class CallTranscript(models.Model):
    _name = "codestra.call.transcript"
    _description = "Redacted Operational Transcript"
    _inherit = ["codestra.call.transcript.scope.mixin"]

    reference = fields.Char(required=True, index=True)
    language = fields.Char(required=True)
    state = fields.Selection([
        ("pending", "Pending"), ("final", "Final"), ("redacted", "Redacted"),
        ("rejected", "Rejected"), ("archived", "Archived"),
    ], default="pending", required=True)
    redacted_text = fields.Text()
    restricted_original_reference = fields.Char()
    recording_reference = fields.Char()
    model_reference = fields.Char()
    source_checksum = fields.Char(required=True)
    _reference_unique = models.Constraint("unique(reference)", "Transcript references must be unique.")


class TranscriptSegment(models.Model):
    _name = "codestra.call.transcript.segment"
    _description = "Transcript Segment"
    _inherit = ["codestra.call.transcript.scope.mixin"]

    transcript_id = fields.Many2one("codestra.call.transcript", required=True, ondelete="cascade")
    sequence = fields.Integer(required=True)
    channel = fields.Char(required=True)
    speaker = fields.Char(required=True)
    start_ms = fields.Integer(required=True)
    end_ms = fields.Integer(required=True)
    confidence = fields.Float(required=True)
    segment_state = fields.Selection([
        ("partial", "Partial"), ("stabilizing", "Stabilizing"), ("final", "Final"),
        ("corrected", "Corrected"), ("redacted", "Redacted"), ("rejected", "Rejected"),
    ], required=True)
    redacted_text = fields.Text()
    _segment_unique = models.Constraint(
        "unique(transcript_id, sequence, channel)", "Transcript segment delivery must be idempotent."
    )


def _scoped_model(model_name, description):
    return type(model_name.replace(".", "_"), (models.Model,), {
        "__module__": __name__,
        "_name": model_name,
        "_description": description,
        "_inherit": ["codestra.call.transcript.scope.mixin"],
        "reference": fields.Char(required=True, index=True),
        "safe_payload": fields.Json(),
        "state": fields.Char(default="disabled", required=True),
    })


Resolution = _scoped_model("codestra.call.resolution", "Call Resolution")
Topic = _scoped_model("codestra.call.topic", "Call Topic")
ActionItem = _scoped_model("codestra.call.action.item", "Call Action Item")
TranscriptionJob = _scoped_model("codestra.call.transcription.job", "Transcription Job")
TranscriptionModel = _scoped_model("codestra.call.transcription.model", "Transcription Model")
TranscriptionEvaluation = _scoped_model("codestra.call.transcription.evaluation", "Transcription Evaluation")
RedactionEvent = _scoped_model("codestra.call.redaction.event", "Transcript Redaction Event")
RecordingAccess = _scoped_model("codestra.call.recording.access", "Recording Access Audit")
SpeechMetric = _scoped_model("codestra.call.speech.metric", "Speech Metric")
