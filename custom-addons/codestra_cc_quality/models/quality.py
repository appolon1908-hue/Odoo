import hashlib
import json
import uuid

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


PROGRAM_WRITE_CAPABILITY = object()
SAMPLE_WRITE_CAPABILITY = object()
EVALUATION_WRITE_CAPABILITY = object()
ANSWER_WRITE_CAPABILITY = object()
CALIBRATION_WRITE_CAPABILITY = object()
DISPUTE_WRITE_CAPABILITY = object()
COACHING_WRITE_CAPABILITY = object()
QUALITY_EVENT_CAPABILITY = object()


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value):
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _is_global_admin(user):
    return user.has_group("codestra_cc_security.group_cc_global_administrator")


def _is_supervisor(user):
    return user.has_group("codestra_cc_security.group_cc_campaign_supervisor")


def _is_qa(user):
    return user.has_group("codestra_cc_security.group_cc_quality_analyst")


def _membership(env, campaign, role, user=None):
    user = user or env.user
    membership = env["cc.campaign.membership"].search(
        [
            ("campaign_id", "=", campaign.id),
            ("user_id", "=", user.id),
            ("role", "=", role),
            ("state", "=", "active"),
        ],
        limit=1,
    )
    if not membership:
        raise AccessError(_("An active same-campaign %(role)s membership is required.", role=role))
    return membership


class CcQualityProgram(models.Model):
    _name = "cc.quality.program"
    _description = "Campaign Quality Program"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "campaign_id, version desc, id desc"

    name = fields.Char(required=True)
    version = fields.Integer(required=True, default=1, copy=False)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("approved", "Approved"),
            ("active", "Active"),
            ("retired", "Retired"),
        ],
        required=True,
        default="draft",
        copy=False,
        index=True,
    )
    requested_by_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user, readonly=True
    )
    approved_by_id = fields.Many2one("res.users", readonly=True, copy=False)
    approved_at = fields.Datetime(readonly=True, copy=False)
    activated_at = fields.Datetime(readonly=True, copy=False)
    source_reference = fields.Char(required=True)
    program_hash = fields.Char(size=64, readonly=True, copy=False, index=True)
    passing_score = fields.Float(required=True, default=85.0)
    critical_fail_score = fields.Float(required=True, default=0.0)
    random_sample_percent = fields.Float(required=True, default=2.0)
    risk_sample_percent = fields.Float(required=True, default=100.0)
    new_agent_sample_percent = fields.Float(required=True, default=100.0)
    separate_finalizer_required = fields.Boolean(required=True, default=True)
    question_ids = fields.One2many("cc.quality.question", "program_id", readonly=True)

    _campaign_version_unique = models.Constraint(
        "unique(campaign_id, version)", "Quality program versions must be unique per campaign."
    )
    _one_active_program = models.UniqueIndex(
        "(campaign_id) WHERE state = 'active'",
        "A campaign may have only one active quality program.",
    )
    _score_bounds = models.Constraint(
        "check(passing_score >= 0 and passing_score <= 100 and critical_fail_score >= 0 and critical_fail_score <= 100)",
        "Quality score thresholds must be between zero and one hundred.",
    )
    _sampling_bounds = models.Constraint(
        "check(random_sample_percent >= 0 and random_sample_percent <= 100 and risk_sample_percent >= 0 and risk_sample_percent <= 100 and new_agent_sample_percent >= 0 and new_agent_sample_percent <= 100)",
        "Quality sample rates must be between zero and one hundred.",
    )

    def _payload(self):
        self.ensure_one()
        return {
            "campaign_uuid": self.campaign_id.workspace_uuid,
            "version": self.version,
            "passing_score": self.passing_score,
            "critical_fail_score": self.critical_fail_score,
            "random_sample_percent": self.random_sample_percent,
            "risk_sample_percent": self.risk_sample_percent,
            "new_agent_sample_percent": self.new_agent_sample_percent,
            "separate_finalizer_required": self.separate_finalizer_required,
            "source_reference": self.source_reference,
            "questions": [
                question._payload() for question in self.question_ids.sorted("sequence")
            ],
        }

    @api.model_create_multi
    def create(self, values_list):
        prepared = []
        for original in values_list:
            values = dict(original)
            forbidden = {
                "approved_by_id",
                "approved_at",
                "activated_at",
                "program_hash",
            }.intersection(values)
            if forbidden or values.get("state", "draft") != "draft":
                raise AccessError(_("New quality programs must enter the governed draft workflow."))
            values.update({"state": "draft", "requested_by_id": self.env.user.id})
            prepared.append(values)
        return super().create(prepared)

    def write(self, values):
        internal = self.env.context.get("_cc_quality_program_capability") is PROGRAM_WRITE_CAPABILITY
        protected = {
            "campaign_id",
            "version",
            "state",
            "program_hash",
            "approved_by_id",
            "approved_at",
            "activated_at",
            "passing_score",
            "critical_fail_score",
            "random_sample_percent",
            "risk_sample_percent",
            "new_agent_sample_percent",
            "separate_finalizer_required",
            "source_reference",
        }
        if not internal and any(program.state != "draft" for program in self) and protected.intersection(values):
            raise AccessError(_("Submitted quality programs are immutable."))
        return super().write(values)

    def unlink(self):
        if any(program.state != "draft" for program in self):
            raise AccessError(_("Submitted quality programs are retained as evidence."))
        return super().unlink()

    def copy(self, default=None):
        raise AccessError(_("Create an explicit new quality program version."))

    def action_submit(self):
        for program in self:
            if program.state != "draft" or not program.question_ids:
                raise ValidationError(_("A draft program with questions is required."))
            if sum(program.question_ids.mapped("weight")) != 100:
                raise ValidationError(_("Quality question weights must total exactly 100."))
            program.with_context(_cc_quality_program_capability=PROGRAM_WRITE_CAPABILITY).write(
                {"state": "submitted", "program_hash": _digest(program._payload())}
            )
        return True

    def action_approve(self):
        for program in self:
            if program.state != "submitted":
                raise ValidationError(_("Only submitted quality programs may be approved."))
            if program.requested_by_id == self.env.user:
                raise ValidationError(_("The program author cannot approve the same version."))
            if program.program_hash != _digest(program._payload()):
                raise ValidationError(_("Quality program content changed after submission."))
            program.with_context(_cc_quality_program_capability=PROGRAM_WRITE_CAPABILITY).write(
                {
                    "state": "approved",
                    "approved_by_id": self.env.user.id,
                    "approved_at": fields.Datetime.now(),
                }
            )
        return True

    def action_activate(self):
        for program in self:
            if program.state != "approved":
                raise ValidationError(_("Only approved quality programs may be activated."))
            if self.search_count(
                [("campaign_id", "=", program.campaign_id.id), ("state", "=", "active")]
            ):
                raise ValidationError(_("Retire the active quality program before activation."))
            program.with_context(_cc_quality_program_capability=PROGRAM_WRITE_CAPABILITY).write(
                {"state": "active", "activated_at": fields.Datetime.now()}
            )
        return True

    def action_retire(self):
        for program in self:
            if program.state not in {"approved", "active"}:
                raise ValidationError(_("Only approved or active quality programs may be retired."))
            program.with_context(_cc_quality_program_capability=PROGRAM_WRITE_CAPABILITY).write(
                {"state": "retired"}
            )
        return True


class CcQualityQuestion(models.Model):
    _name = "cc.quality.question"
    _description = "Versioned Quality Scorecard Question"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "program_id, sequence, id"

    program_id = fields.Many2one(
        "cc.quality.program", required=True, ondelete="restrict", index=True
    )
    sequence = fields.Integer(required=True, default=10)
    code = fields.Char(required=True, index=True)
    text = fields.Char(required=True)
    weight = fields.Integer(required=True)
    maximum_points = fields.Float(required=True, default=1.0)
    required = fields.Boolean(required=True, default=True)
    critical_fail = fields.Boolean(required=True, default=False)
    guidance = fields.Text()

    _question_code_unique = models.Constraint(
        "unique(program_id, code)", "Question codes must be unique inside a quality program."
    )
    _positive_weight = models.Constraint(
        "check(weight > 0 and weight <= 100 and maximum_points > 0)",
        "Question weight and maximum points must be positive.",
    )

    @api.model_create_multi
    def create(self, values_list):
        records = super().create(values_list)
        records._check_question_scope()
        return records

    def write(self, values):
        if any(question.program_id.state != "draft" for question in self):
            raise AccessError(_("Questions are immutable after program submission."))
        result = super().write(values)
        self._check_question_scope()
        return result

    def unlink(self):
        if any(question.program_id.state != "draft" for question in self):
            raise AccessError(_("Approved scorecard questions cannot be deleted."))
        return super().unlink()

    def copy(self, default=None):
        raise AccessError(_("Scorecard questions require an explicit version."))

    @api.constrains("campaign_id", "program_id")
    def _check_question_scope(self):
        for question in self:
            if question.program_id.campaign_id != question.campaign_id:
                raise ValidationError(_("Question and quality program campaigns differ."))

    def _payload(self):
        self.ensure_one()
        return {
            "sequence": self.sequence,
            "code": self.code,
            "text": self.text,
            "weight": self.weight,
            "maximum_points": self.maximum_points,
            "required": self.required,
            "critical_fail": self.critical_fail,
            "guidance": self.guidance,
        }


class CcQualitySample(models.Model):
    _name = "cc.quality.sample"
    _description = "Campaign Quality Sample"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "assigned_at desc, id desc"

    reference = fields.Char(
        required=True, default=lambda self: str(uuid.uuid4()), readonly=True, copy=False, index=True
    )
    program_id = fields.Many2one(
        "cc.quality.program", required=True, readonly=True, ondelete="restrict"
    )
    recording_id = fields.Many2one(
        "cc.recording", required=True, readonly=True, ondelete="restrict", index=True
    )
    agent_membership_id = fields.Many2one(
        "cc.campaign.membership", required=True, readonly=True, ondelete="restrict", index=True
    )
    assigned_qa_membership_id = fields.Many2one(
        "cc.campaign.membership", required=True, readonly=True, ondelete="restrict", index=True
    )
    sample_reason = fields.Selection(
        [
            ("random", "Random"),
            ("risk", "Risk-Based"),
            ("new_agent", "New Agent"),
            ("complaint", "Complaint"),
            ("calibration", "Calibration"),
        ],
        required=True,
        readonly=True,
        index=True,
    )
    reason_reference_hash = fields.Char(required=True, size=64, readonly=True)
    state = fields.Selection(
        [
            ("assigned", "Assigned"),
            ("in_review", "In Review"),
            ("evaluated", "Evaluated"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="assigned",
        readonly=True,
        index=True,
    )
    assigned_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    evaluation_ids = fields.One2many("cc.quality.evaluation", "sample_id", readonly=True)

    _reference_unique = models.Constraint(
        "unique(reference)", "Quality sample references must be unique."
    )
    _recording_program_unique = models.Constraint(
        "unique(recording_id, program_id)",
        "A recording may be sampled only once per quality program version.",
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_quality_sample_capability") is not SAMPLE_WRITE_CAPABILITY:
            raise AccessError(_("Quality samples require the governed assignment workflow."))
        records = super().create(values_list)
        records._check_sample_scope()
        return records.with_context(_cc_quality_sample_capability=None)

    def write(self, values):
        if self.env.context.get("_cc_quality_sample_capability") is not SAMPLE_WRITE_CAPABILITY:
            raise AccessError(_("Quality sample lifecycle requires a governed action."))
        result = super().write(values)
        self._check_sample_scope()
        return result

    def unlink(self):
        raise AccessError(_("Quality samples are retained as evidence."))

    def copy(self, default=None):
        raise AccessError(_("Quality samples cannot be copied."))

    @api.constrains(
        "campaign_id", "program_id", "recording_id", "agent_membership_id", "assigned_qa_membership_id"
    )
    def _check_sample_scope(self):
        for sample in self:
            if sample.program_id.campaign_id != sample.campaign_id or sample.program_id.state != "active":
                raise ValidationError(_("Quality sample requires the active same-campaign program."))
            if sample.recording_id.campaign_id != sample.campaign_id:
                raise ValidationError(_("Quality sample recording belongs to another campaign."))
            if sample.agent_membership_id != sample.recording_id.agent_membership_id:
                raise ValidationError(_("Quality sample agent does not match the recording binding."))
            qa = sample.assigned_qa_membership_id
            if qa.campaign_id != sample.campaign_id or qa.role != "qa" or qa.state != "active":
                raise ValidationError(_("Quality sample must be assigned to active same-campaign QA."))

    @api.model
    def assign_sample(
        self,
        *,
        program_id,
        recording_id,
        assigned_qa_membership_id,
        sample_reason,
        reason_reference,
    ):
        program = self.env["cc.quality.program"].browse(program_id).exists()
        recording = self.env["cc.recording"].browse(recording_id).exists()
        qa = self.env["cc.campaign.membership"].browse(assigned_qa_membership_id).exists()
        if not program or not recording or not qa:
            raise ValidationError(_("Quality sample assignment is incomplete."))
        if not (_is_global_admin(self.env.user) or _is_supervisor(self.env.user)):
            raise AccessError(_("Only a campaign supervisor or global administrator may assign samples."))
        if _is_supervisor(self.env.user) and not _is_global_admin(self.env.user):
            _membership(self.env, program.campaign_id, "supervisor")
        if program.state != "active" or recording.campaign_id != program.campaign_id:
            raise ValidationError(
                _("Quality samples require an active program and recording in one campaign.")
            )
        if (
            qa.campaign_id != program.campaign_id
            or qa.role != "qa"
            or qa.state != "active"
        ):
            raise ValidationError(
                _("Quality samples require active QA membership in the same campaign.")
            )
        if recording.agent_membership_id.campaign_id != program.campaign_id:
            raise ValidationError(
                _("The recorded agent membership belongs to another campaign.")
            )
        reason_reference = str(reason_reference or "").strip()
        if not reason_reference:
            raise ValidationError(_("Sampling requires a controlled reason reference."))
        return self.with_context(_cc_quality_sample_capability=SAMPLE_WRITE_CAPABILITY).create(
            {
                "campaign_id": program.campaign_id.id,
                "program_id": program.id,
                "recording_id": recording.id,
                "agent_membership_id": recording.agent_membership_id.id,
                "assigned_qa_membership_id": qa.id,
                "sample_reason": sample_reason,
                "reason_reference_hash": hashlib.sha256(reason_reference.encode("utf-8")).hexdigest(),
            }
        )

    def action_start_review(self):
        for sample in self:
            if sample.state != "assigned":
                raise ValidationError(_("Only assigned samples may enter review."))
            if sample.assigned_qa_membership_id.user_id != self.env.user:
                raise AccessError(_("Only the assigned QA analyst may start the review."))
            sample.with_context(_cc_quality_sample_capability=SAMPLE_WRITE_CAPABILITY).write(
                {"state": "in_review"}
            )
        return True


class CcQualityEvaluation(models.Model):
    _name = "cc.quality.evaluation"
    _description = "Versioned Quality Evaluation"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "sample_id, version desc, id desc"

    reference = fields.Char(
        required=True, default=lambda self: str(uuid.uuid4()), readonly=True, copy=False, index=True
    )
    sample_id = fields.Many2one(
        "cc.quality.sample", required=True, readonly=True, ondelete="restrict", index=True
    )
    agent_membership_id = fields.Many2one(
        related="sample_id.agent_membership_id", store=True, readonly=True, index=True
    )
    version = fields.Integer(required=True, default=1, readonly=True, copy=False)
    supersedes_id = fields.Many2one(
        "cc.quality.evaluation", readonly=True, ondelete="restrict", copy=False
    )
    correction_reason_hash = fields.Char(size=64, readonly=True, copy=False)
    evaluator_membership_id = fields.Many2one(
        "cc.campaign.membership",
        required=True,
        readonly=True,
        ondelete="restrict",
        groups=(
            "codestra_cc_security.group_cc_quality_analyst,"
            "codestra_cc_security.group_cc_campaign_supervisor,"
            "codestra_cc_security.group_cc_auditor,"
            "codestra_cc_security.group_cc_global_administrator"
        ),
    )
    finalizer_membership_id = fields.Many2one(
        "cc.campaign.membership",
        readonly=True,
        ondelete="restrict",
        copy=False,
        groups=(
            "codestra_cc_security.group_cc_quality_analyst,"
            "codestra_cc_security.group_cc_campaign_supervisor,"
            "codestra_cc_security.group_cc_auditor,"
            "codestra_cc_security.group_cc_global_administrator"
        ),
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("finalized", "Finalized"),
            ("superseded", "Superseded"),
        ],
        required=True,
        default="draft",
        readonly=True,
        index=True,
    )
    score = fields.Float(readonly=True)
    critical_failed = fields.Boolean(readonly=True)
    evaluation_hash = fields.Char(size=64, readonly=True, copy=False, index=True)
    submitted_at = fields.Datetime(readonly=True, copy=False)
    finalized_at = fields.Datetime(readonly=True, copy=False)
    answer_ids = fields.One2many("cc.quality.answer", "evaluation_id", readonly=True)

    _reference_unique = models.Constraint(
        "unique(reference)", "Quality evaluation references must be unique."
    )
    _sample_version_unique = models.Constraint(
        "unique(sample_id, version)", "Quality evaluation versions must be unique per sample."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_quality_evaluation_capability") is not EVALUATION_WRITE_CAPABILITY:
            raise AccessError(_("Evaluations require the governed quality workflow."))
        records = super().create(values_list)
        records._check_evaluation_scope()
        return records.with_context(_cc_quality_evaluation_capability=None)

    def write(self, values):
        if self.env.context.get("_cc_quality_evaluation_capability") is not EVALUATION_WRITE_CAPABILITY:
            raise AccessError(_("Evaluation lifecycle requires the governed quality workflow."))
        result = super().write(values)
        self._check_evaluation_scope()
        return result

    def unlink(self):
        raise AccessError(_("Quality evaluations are retained as signed evidence."))

    def copy(self, default=None):
        raise AccessError(_("Evaluation corrections require a superseding version."))

    @api.constrains(
        "campaign_id", "sample_id", "evaluator_membership_id", "finalizer_membership_id", "supersedes_id"
    )
    def _check_evaluation_scope(self):
        for evaluation in self:
            if evaluation.sample_id.campaign_id != evaluation.campaign_id:
                raise ValidationError(_("Evaluation and sample campaigns differ."))
            evaluator = evaluation.evaluator_membership_id
            if evaluator.campaign_id != evaluation.campaign_id or evaluator.role != "qa" or evaluator.state != "active":
                raise ValidationError(_("Evaluation author must be active same-campaign QA."))
            finalizer = evaluation.finalizer_membership_id
            if finalizer and (
                finalizer.campaign_id != evaluation.campaign_id
                or finalizer.role != "qa"
                or finalizer.state != "active"
            ):
                raise ValidationError(_("Evaluation finalizer must be active same-campaign QA."))
            if evaluation.supersedes_id and evaluation.supersedes_id.sample_id != evaluation.sample_id:
                raise ValidationError(_("A correction may supersede only the same quality sample."))

    @api.model
    def begin_for_sample(self, sample):
        sample.ensure_one()
        if sample.state not in {"assigned", "in_review"}:
            raise ValidationError(_("The sample is not available for evaluation."))
        evaluator = _membership(self.env, sample.campaign_id, "qa")
        if sample.assigned_qa_membership_id != evaluator:
            raise AccessError(_("Only the assigned QA analyst may author this evaluation."))
        existing = self.search([("sample_id", "=", sample.id), ("state", "in", ["draft", "submitted"])], limit=1)
        if existing:
            return existing
        if sample.state == "assigned":
            sample.action_start_review()
        return self.with_context(_cc_quality_evaluation_capability=EVALUATION_WRITE_CAPABILITY).create(
            {
                "campaign_id": sample.campaign_id.id,
                "sample_id": sample.id,
                "evaluator_membership_id": evaluator.id,
            }
        )

    def set_answer(self, question, points, result, note=""):
        self.ensure_one()
        question.ensure_one()
        if self.state != "draft" or self.evaluator_membership_id.user_id != self.env.user:
            raise AccessError(_("Only the evaluation author may score a draft evaluation."))
        if question.program_id != self.sample_id.program_id or question.campaign_id != self.campaign_id:
            raise ValidationError(_("The scorecard question belongs to another quality program."))
        if result not in {"pass", "fail", "not_applicable"}:
            raise ValidationError(_("Unsupported quality answer result."))
        points = float(points)
        if points < 0 or points > question.maximum_points:
            raise ValidationError(_("Quality answer points exceed the question maximum."))
        existing = self.answer_ids.filtered(lambda answer: answer.question_id == question)
        values = {
            "campaign_id": self.campaign_id.id,
            "evaluation_id": self.id,
            "question_id": question.id,
            "points": points,
            "result": result,
            "safe_note": str(note or "")[:500],
        }
        if existing:
            existing.with_context(_cc_quality_answer_capability=ANSWER_WRITE_CAPABILITY).write(values)
            return existing
        return self.env["cc.quality.answer"].with_context(
            _cc_quality_answer_capability=ANSWER_WRITE_CAPABILITY
        ).create(values)

    def _scored_payload(self):
        self.ensure_one()
        return {
            "reference": self.reference,
            "sample_reference": self.sample_id.reference,
            "version": self.version,
            "program_hash": self.sample_id.program_id.program_hash,
            "answers": [
                answer._payload()
                for answer in self.answer_ids.sorted(
                    key=lambda row: (row.question_id.sequence, row.id)
                )
            ],
        }

    def action_submit(self):
        for evaluation in self:
            if evaluation.state != "draft" or evaluation.evaluator_membership_id.user_id != self.env.user:
                raise AccessError(_("Only the author may submit a draft evaluation."))
            required_questions = evaluation.sample_id.program_id.question_ids.filtered("required")
            if set(required_questions.ids) != set(evaluation.answer_ids.mapped("question_id").ids):
                raise ValidationError(_("Every required scorecard question must be answered."))
            score = 0.0
            critical_failed = False
            for answer in evaluation.answer_ids:
                question = answer.question_id
                normalized = 0.0 if answer.result == "not_applicable" else answer.points / question.maximum_points
                score += normalized * question.weight
                critical_failed = critical_failed or (
                    question.critical_fail and answer.result == "fail"
                )
            if critical_failed:
                score = min(score, evaluation.sample_id.program_id.critical_fail_score)
            evaluation_hash = _digest(evaluation._scored_payload())
            evaluation.with_context(_cc_quality_evaluation_capability=EVALUATION_WRITE_CAPABILITY).write(
                {
                    "state": "submitted",
                    "score": round(score, 2),
                    "critical_failed": critical_failed,
                    "evaluation_hash": evaluation_hash,
                    "submitted_at": fields.Datetime.now(),
                }
            )
            self.env["cc.quality.event"]._append(
                evaluation.campaign_id,
                "evaluation_submitted",
                evaluation._name,
                evaluation.id,
                evaluation.agent_membership_id,
                evaluation_hash,
            )
        return True

    def action_finalize(self):
        for evaluation in self:
            if evaluation.state != "submitted":
                raise ValidationError(_("Only submitted evaluations may be finalized."))
            finalizer = _membership(self.env, evaluation.campaign_id, "qa")
            if evaluation.sample_id.program_id.separate_finalizer_required and (
                finalizer == evaluation.evaluator_membership_id
            ):
                raise ValidationError(_("A separate QA analyst must finalize this evaluation."))
            if evaluation.evaluation_hash != _digest(evaluation._scored_payload()):
                raise ValidationError(_("Evaluation answers changed after submission."))
            evaluation.with_context(_cc_quality_evaluation_capability=EVALUATION_WRITE_CAPABILITY).write(
                {
                    "state": "finalized",
                    "finalizer_membership_id": finalizer.id,
                    "finalized_at": fields.Datetime.now(),
                }
            )
            evaluation.sample_id.with_context(
                _cc_quality_sample_capability=SAMPLE_WRITE_CAPABILITY
            ).write({"state": "evaluated"})
            self.env["cc.quality.event"]._append(
                evaluation.campaign_id,
                "evaluation_finalized",
                evaluation._name,
                evaluation.id,
                evaluation.agent_membership_id,
                evaluation.evaluation_hash,
            )
        return True

    def action_create_correction(self, reason):
        self.ensure_one()
        if self.state != "finalized" or not _is_qa(self.env.user):
            raise AccessError(_("Only QA may create a correction to a finalized evaluation."))
        reason = str(reason or "").strip()
        if not reason:
            raise ValidationError(_("A correction reason is required."))
        evaluator = _membership(self.env, self.campaign_id, "qa")
        correction = self.with_context(
            _cc_quality_evaluation_capability=EVALUATION_WRITE_CAPABILITY
        ).create(
            {
                "campaign_id": self.campaign_id.id,
                "sample_id": self.sample_id.id,
                "version": self.version + 1,
                "supersedes_id": self.id,
                "correction_reason_hash": hashlib.sha256(reason.encode("utf-8")).hexdigest(),
                "evaluator_membership_id": evaluator.id,
            }
        )
        for answer in self.answer_ids:
            correction.set_answer(
                answer.question_id, answer.points, answer.result, answer.safe_note
            )
        return correction

    def action_acknowledge(self):
        for evaluation in self:
            if evaluation.state != "finalized":
                raise ValidationError(_("Only finalized evaluations may be acknowledged."))
            agent = _membership(self.env, evaluation.campaign_id, "agent")
            if agent != evaluation.agent_membership_id:
                raise AccessError(_("Only the evaluated agent may acknowledge the result."))
            self.env["cc.quality.event"]._append(
                evaluation.campaign_id,
                "evaluation_acknowledged",
                evaluation._name,
                evaluation.id,
                agent,
                evaluation.evaluation_hash,
            )
        return True

    def action_open_dispute(self, reason):
        self.ensure_one()
        if self.state != "finalized":
            raise ValidationError(_("Only a finalized evaluation may be disputed."))
        agent = _membership(self.env, self.campaign_id, "agent")
        if agent != self.agent_membership_id:
            raise AccessError(_("Only the evaluated agent may open the dispute."))
        return self.env["cc.quality.dispute"]._open(self, agent, reason)


class CcQualityAnswer(models.Model):
    _name = "cc.quality.answer"
    _description = "Quality Evaluation Answer"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "question_id, id"

    evaluation_id = fields.Many2one(
        "cc.quality.evaluation", required=True, readonly=True, ondelete="restrict", index=True
    )
    question_id = fields.Many2one(
        "cc.quality.question", required=True, readonly=True, ondelete="restrict"
    )
    points = fields.Float(required=True)
    result = fields.Selection(
        [("pass", "Pass"), ("fail", "Fail"), ("not_applicable", "Not Applicable")],
        required=True,
    )
    safe_note = fields.Text()

    _evaluation_question_unique = models.Constraint(
        "unique(evaluation_id, question_id)", "Each scorecard question may be answered once."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_quality_answer_capability") is not ANSWER_WRITE_CAPABILITY:
            raise AccessError(_("Quality answers require the evaluation workflow."))
        records = super().create(values_list)
        records._check_answer_scope()
        return records.with_context(_cc_quality_answer_capability=None)

    def write(self, values):
        if self.env.context.get("_cc_quality_answer_capability") is not ANSWER_WRITE_CAPABILITY:
            raise AccessError(_("Quality answers require the evaluation workflow."))
        if any(answer.evaluation_id.state != "draft" for answer in self):
            raise AccessError(_("Submitted evaluation answers are immutable."))
        result = super().write(values)
        self._check_answer_scope()
        return result

    def unlink(self):
        raise AccessError(_("Quality answers are retained as evidence."))

    @api.constrains("campaign_id", "evaluation_id", "question_id")
    def _check_answer_scope(self):
        for answer in self:
            if answer.evaluation_id.campaign_id != answer.campaign_id or (
                answer.question_id.campaign_id != answer.campaign_id
            ):
                raise ValidationError(_("Quality answer scope mismatch."))
            if answer.question_id.program_id != answer.evaluation_id.sample_id.program_id:
                raise ValidationError(_("Quality answer uses a question from another program."))

    def _payload(self):
        self.ensure_one()
        return {
            "question_code": self.question_id.code,
            "points": self.points,
            "result": self.result,
            "safe_note": self.safe_note,
        }


class CcQualityCalibration(models.Model):
    _name = "cc.quality.calibration"
    _description = "Quality Calibration Session"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "scheduled_at desc, id desc"

    reference = fields.Char(
        required=True, default=lambda self: str(uuid.uuid4()), readonly=True, copy=False, index=True
    )
    program_id = fields.Many2one(
        "cc.quality.program", required=True, readonly=True, ondelete="restrict"
    )
    evaluation_ids = fields.Many2many(
        "cc.quality.evaluation", string="Finalized Evaluations", readonly=True
    )
    facilitator_membership_id = fields.Many2one(
        "cc.campaign.membership", required=True, readonly=True, ondelete="restrict"
    )
    scheduled_at = fields.Datetime(required=True, readonly=True)
    state = fields.Selection(
        [("scheduled", "Scheduled"), ("completed", "Completed"), ("cancelled", "Cancelled")],
        required=True,
        default="scheduled",
        readonly=True,
    )
    variance = fields.Float(readonly=True)
    outcome_hash = fields.Char(size=64, readonly=True)
    completed_at = fields.Datetime(readonly=True)

    _reference_unique = models.Constraint(
        "unique(reference)", "Calibration references must be unique."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_quality_calibration_capability") is not CALIBRATION_WRITE_CAPABILITY:
            raise AccessError(_("Calibration sessions require the governed scheduling workflow."))
        records = super().create(values_list)
        records._check_calibration_scope()
        return records.with_context(_cc_quality_calibration_capability=None)

    def write(self, values):
        if self.env.context.get("_cc_quality_calibration_capability") is not CALIBRATION_WRITE_CAPABILITY:
            raise AccessError(_("Calibration lifecycle requires a governed action."))
        result = super().write(values)
        self._check_calibration_scope()
        return result

    def unlink(self):
        raise AccessError(_("Calibration evidence cannot be deleted."))

    @api.constrains("campaign_id", "program_id", "evaluation_ids", "facilitator_membership_id")
    def _check_calibration_scope(self):
        for calibration in self:
            if calibration.program_id.campaign_id != calibration.campaign_id:
                raise ValidationError(_("Calibration program belongs to another campaign."))
            if any(evaluation.campaign_id != calibration.campaign_id for evaluation in calibration.evaluation_ids):
                raise ValidationError(_("Calibration evaluations cannot cross campaigns."))
            facilitator = calibration.facilitator_membership_id
            if facilitator.campaign_id != calibration.campaign_id or facilitator.role != "supervisor":
                raise ValidationError(_("Calibration facilitator must be the campaign supervisor."))

    @api.model
    def schedule_calibration(self, program, evaluations, scheduled_at):
        program.ensure_one()
        if not evaluations or not scheduled_at:
            raise ValidationError(_("Calibration evaluations and schedule are required."))
        facilitator = _membership(self.env, program.campaign_id, "supervisor")
        return self.with_context(
            _cc_quality_calibration_capability=CALIBRATION_WRITE_CAPABILITY
        ).create(
            {
                "campaign_id": program.campaign_id.id,
                "program_id": program.id,
                "evaluation_ids": [(6, 0, evaluations.ids)],
                "facilitator_membership_id": facilitator.id,
                "scheduled_at": scheduled_at,
            }
        )

    def action_complete(self):
        for calibration in self:
            if calibration.state != "scheduled" or not calibration.evaluation_ids:
                raise ValidationError(_("A scheduled calibration with evaluations is required."))
            if any(evaluation.state != "finalized" for evaluation in calibration.evaluation_ids):
                raise ValidationError(_("Calibration accepts finalized evaluations only."))
            if calibration.facilitator_membership_id.user_id != self.env.user and not _is_global_admin(
                self.env.user
            ):
                raise AccessError(_("Only the calibration facilitator may complete the session."))
            scores = calibration.evaluation_ids.mapped("score")
            variance = max(scores) - min(scores)
            payload_hash = _digest(
                {
                    "reference": calibration.reference,
                    "program_hash": calibration.program_id.program_hash,
                    "evaluation_hashes": sorted(calibration.evaluation_ids.mapped("evaluation_hash")),
                    "variance": variance,
                }
            )
            calibration.with_context(
                _cc_quality_calibration_capability=CALIBRATION_WRITE_CAPABILITY
            ).write(
                {
                    "state": "completed",
                    "variance": variance,
                    "outcome_hash": payload_hash,
                    "completed_at": fields.Datetime.now(),
                }
            )
        return True


class CcQualityDispute(models.Model):
    _name = "cc.quality.dispute"
    _description = "Quality Evaluation Dispute"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "opened_at desc, id desc"

    reference = fields.Char(
        required=True, default=lambda self: str(uuid.uuid4()), readonly=True, copy=False, index=True
    )
    evaluation_id = fields.Many2one(
        "cc.quality.evaluation", required=True, readonly=True, ondelete="restrict", index=True
    )
    agent_membership_id = fields.Many2one(
        "cc.campaign.membership", required=True, readonly=True, ondelete="restrict"
    )
    reason_hash = fields.Char(required=True, size=64, readonly=True)
    state = fields.Selection(
        [("open", "Open"), ("upheld", "Upheld"), ("denied", "Denied")],
        required=True,
        default="open",
        readonly=True,
    )
    opened_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    resolved_by_membership_id = fields.Many2one(
        "cc.campaign.membership", readonly=True, ondelete="restrict"
    )
    resolution_hash = fields.Char(size=64, readonly=True)
    resolved_at = fields.Datetime(readonly=True)

    _reference_unique = models.Constraint(
        "unique(reference)", "Quality dispute references must be unique."
    )
    _one_dispute_evaluation = models.Constraint(
        "unique(evaluation_id)", "A finalized evaluation may have only one dispute."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_quality_dispute_capability") is not DISPUTE_WRITE_CAPABILITY:
            raise AccessError(_("Quality disputes require the governed dispute workflow."))
        return super().create(values_list).with_context(
            _cc_quality_dispute_capability=None
        )

    def write(self, values):
        if self.env.context.get("_cc_quality_dispute_capability") is not DISPUTE_WRITE_CAPABILITY:
            raise AccessError(_("Quality dispute resolution requires a governed action."))
        return super().write(values)

    def unlink(self):
        raise AccessError(_("Quality disputes are retained as evidence."))

    @api.model
    def _open(self, evaluation, agent, reason):
        reason = str(reason or "").strip()
        if not reason:
            raise ValidationError(_("A dispute reason is required."))
        dispute = self.with_context(_cc_quality_dispute_capability=DISPUTE_WRITE_CAPABILITY).create(
            {
                "campaign_id": evaluation.campaign_id.id,
                "evaluation_id": evaluation.id,
                "agent_membership_id": agent.id,
                "reason_hash": hashlib.sha256(reason.encode("utf-8")).hexdigest(),
            }
        )
        self.env["cc.quality.event"]._append(
            evaluation.campaign_id,
            "dispute_opened",
            dispute._name,
            dispute.id,
            agent,
            dispute.reason_hash,
        )
        return dispute

    def action_resolve(self, outcome, resolution):
        if outcome not in {"upheld", "denied"}:
            raise ValidationError(_("Dispute outcome must be upheld or denied."))
        resolution = str(resolution or "").strip()
        if not resolution:
            raise ValidationError(_("Dispute resolution evidence is required."))
        for dispute in self:
            if dispute.state != "open":
                raise ValidationError(_("Only open disputes may be resolved."))
            resolver = _membership(self.env, dispute.campaign_id, "qa")
            if resolver == dispute.evaluation_id.evaluator_membership_id:
                raise ValidationError(_("The evaluation author cannot resolve the dispute."))
            resolution_hash = hashlib.sha256(resolution.encode("utf-8")).hexdigest()
            dispute.with_context(_cc_quality_dispute_capability=DISPUTE_WRITE_CAPABILITY).write(
                {
                    "state": outcome,
                    "resolved_by_membership_id": resolver.id,
                    "resolution_hash": resolution_hash,
                    "resolved_at": fields.Datetime.now(),
                }
            )
        return True


class CcCoachingPlan(models.Model):
    _name = "cc.coaching.plan"
    _description = "Campaign Coaching Plan"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "due_at, id"

    reference = fields.Char(
        required=True, default=lambda self: str(uuid.uuid4()), readonly=True, copy=False, index=True
    )
    evaluation_id = fields.Many2one(
        "cc.quality.evaluation", required=True, readonly=True, ondelete="restrict", index=True
    )
    agent_membership_id = fields.Many2one(
        "cc.campaign.membership", required=True, readonly=True, ondelete="restrict", index=True
    )
    owner_membership_id = fields.Many2one(
        "cc.campaign.membership", required=True, readonly=True, ondelete="restrict"
    )
    objective = fields.Char(required=True, readonly=True)
    due_at = fields.Datetime(required=True, readonly=True, index=True)
    recording_sample_allowed = fields.Boolean(required=True, default=False, readonly=True)
    state = fields.Selection(
        [
            ("assigned", "Assigned"),
            ("acknowledged", "Acknowledged"),
            ("completed", "Completed"),
            ("effectiveness_reviewed", "Effectiveness Reviewed"),
        ],
        required=True,
        default="assigned",
        readonly=True,
        index=True,
    )
    acknowledgement_at = fields.Datetime(readonly=True)
    completion_evidence_hash = fields.Char(size=64, readonly=True)
    completed_at = fields.Datetime(readonly=True)
    effectiveness_result = fields.Selection(
        [("effective", "Effective"), ("partial", "Partially Effective"), ("ineffective", "Ineffective")],
        readonly=True,
    )
    effectiveness_evidence_hash = fields.Char(size=64, readonly=True)
    reviewed_at = fields.Datetime(readonly=True)

    _reference_unique = models.Constraint(
        "unique(reference)", "Coaching plan references must be unique."
    )
    _one_plan_evaluation = models.Constraint(
        "unique(evaluation_id)", "A finalized evaluation may have only one coaching plan."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_coaching_write_capability") is not COACHING_WRITE_CAPABILITY:
            raise AccessError(_("Coaching plans require the governed assignment workflow."))
        records = super().create(values_list)
        records._check_coaching_scope()
        return records.with_context(_cc_coaching_write_capability=None)

    def write(self, values):
        if self.env.context.get("_cc_coaching_write_capability") is not COACHING_WRITE_CAPABILITY:
            raise AccessError(_("Coaching lifecycle requires a governed action."))
        result = super().write(values)
        self._check_coaching_scope()
        return result

    def unlink(self):
        raise AccessError(_("Coaching plans are retained as evidence."))

    @api.constrains("campaign_id", "evaluation_id", "agent_membership_id", "owner_membership_id")
    def _check_coaching_scope(self):
        for plan in self:
            evaluation = plan.evaluation_id
            if evaluation.campaign_id != plan.campaign_id or evaluation.state != "finalized":
                raise ValidationError(_("Coaching requires a finalized same-campaign evaluation."))
            if plan.agent_membership_id != evaluation.sample_id.agent_membership_id:
                raise ValidationError(_("Coaching agent does not match the evaluation."))
            owner = plan.owner_membership_id
            if owner.campaign_id != plan.campaign_id or owner.role != "supervisor" or owner.state != "active":
                raise ValidationError(_("Coaching owner must be the active campaign supervisor."))
            if plan.recording_sample_allowed and not evaluation.sample_id.recording_id.policy_id.agent_coaching_replay_allowed:
                raise ValidationError(_("The recording policy does not permit an agent coaching sample."))

    @api.model
    def create_for_evaluation(self, evaluation, objective, due_at):
        evaluation.ensure_one()
        if evaluation.state != "finalized":
            raise ValidationError(_("Coaching requires a finalized evaluation."))
        owner = _membership(self.env, evaluation.campaign_id, "supervisor")
        objective = str(objective or "").strip()
        if not objective or not due_at:
            raise ValidationError(_("Coaching objective and due date are required."))
        return self.with_context(_cc_coaching_write_capability=COACHING_WRITE_CAPABILITY).create(
            {
                "campaign_id": evaluation.campaign_id.id,
                "evaluation_id": evaluation.id,
                "agent_membership_id": evaluation.sample_id.agent_membership_id.id,
                "owner_membership_id": owner.id,
                "objective": objective,
                "due_at": due_at,
                "recording_sample_allowed": False,
            }
        )

    def action_acknowledge(self):
        for plan in self:
            agent = _membership(self.env, plan.campaign_id, "agent")
            if agent != plan.agent_membership_id or plan.state != "assigned":
                raise AccessError(_("Only the assigned agent may acknowledge this coaching plan."))
            plan.with_context(_cc_coaching_write_capability=COACHING_WRITE_CAPABILITY).write(
                {"state": "acknowledged", "acknowledgement_at": fields.Datetime.now()}
            )
            self.env["cc.quality.event"]._append(
                plan.campaign_id,
                "coaching_acknowledged",
                plan._name,
                plan.id,
                agent,
                plan.reference,
            )
        return True

    def action_complete(self, evidence):
        evidence = str(evidence or "").strip()
        if not evidence:
            raise ValidationError(_("Coaching completion evidence is required."))
        for plan in self:
            if plan.owner_membership_id.user_id != self.env.user or plan.state != "acknowledged":
                raise AccessError(_("Only the coaching owner may complete an acknowledged plan."))
            plan.with_context(_cc_coaching_write_capability=COACHING_WRITE_CAPABILITY).write(
                {
                    "state": "completed",
                    "completion_evidence_hash": hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
                    "completed_at": fields.Datetime.now(),
                }
            )
        return True

    def action_review_effectiveness(self, result, evidence):
        if result not in {"effective", "partial", "ineffective"}:
            raise ValidationError(_("Unsupported coaching effectiveness result."))
        evidence = str(evidence or "").strip()
        if not evidence:
            raise ValidationError(_("Effectiveness review evidence is required."))
        for plan in self:
            if plan.owner_membership_id.user_id != self.env.user or plan.state != "completed":
                raise AccessError(_("Only the coaching owner may review a completed plan."))
            plan.with_context(_cc_coaching_write_capability=COACHING_WRITE_CAPABILITY).write(
                {
                    "state": "effectiveness_reviewed",
                    "effectiveness_result": result,
                    "effectiveness_evidence_hash": hashlib.sha256(evidence.encode("utf-8")).hexdigest(),
                    "reviewed_at": fields.Datetime.now(),
                }
            )
        return True


class CcQualityEvent(models.Model):
    _name = "cc.quality.event"
    _description = "Append-Only Quality and Coaching Event"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "occurred_at desc, id desc"

    event_uuid = fields.Char(required=True, readonly=True, copy=False, index=True)
    event_type = fields.Selection(
        [
            ("evaluation_submitted", "Evaluation Submitted"),
            ("evaluation_finalized", "Evaluation Finalized"),
            ("evaluation_acknowledged", "Evaluation Acknowledged"),
            ("dispute_opened", "Dispute Opened"),
            ("coaching_acknowledged", "Coaching Acknowledged"),
        ],
        required=True,
        readonly=True,
        index=True,
    )
    aggregate_model = fields.Char(required=True, readonly=True)
    aggregate_id = fields.Integer(required=True, readonly=True)
    actor_id = fields.Many2one(
        "res.users", required=True, readonly=True, ondelete="restrict", index=True
    )
    subject_membership_id = fields.Many2one(
        "cc.campaign.membership", readonly=True, ondelete="restrict", index=True
    )
    evidence_hash = fields.Char(required=True, size=64, readonly=True)
    occurred_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)

    _event_uuid_unique = models.Constraint(
        "unique(event_uuid)", "Quality event UUIDs must be unique."
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get("_cc_quality_event_capability") is not QUALITY_EVENT_CAPABILITY:
            raise AccessError(_("Quality evidence requires the governed workflow."))
        return super().create(values_list).with_context(
            _cc_quality_event_capability=None
        )

    def write(self, values):
        raise AccessError(_("Quality evidence is immutable."))

    def unlink(self):
        raise AccessError(_("Quality evidence cannot be deleted."))

    @api.model
    def _append(
        self,
        campaign,
        event_type,
        aggregate_model,
        aggregate_id,
        subject_membership,
        evidence,
    ):
        evidence_hash = evidence if len(str(evidence or "")) == 64 else _digest(evidence)
        event_uuid = hashlib.sha256(
            f"{event_type}:{aggregate_model}:{aggregate_id}:{self.env.user.id}:{fields.Datetime.now()}".encode(
                "utf-8"
            )
        ).hexdigest()
        return self.with_context(_cc_quality_event_capability=QUALITY_EVENT_CAPABILITY).create(
            {
                "campaign_id": campaign.id,
                "event_uuid": event_uuid,
                "event_type": event_type,
                "aggregate_model": aggregate_model,
                "aggregate_id": aggregate_id,
                "actor_id": self.env.user.id,
                "subject_membership_id": subject_membership.id if subject_membership else False,
                "evidence_hash": evidence_hash,
            }
        )
