from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestRecordingAndQualityWorkflow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["cc.business.unit"]._adopt_legacy_records()
        cls.Campaign = cls.env["cc.campaign"].with_context(active_test=False)
        cls.campaign_a = cls.Campaign.search([("code", "=", "COD-WEB-OUT")], limit=1)
        cls.campaign_b = cls.Campaign.search([("id", "!=", cls.campaign_a.id)], limit=1)
        cls.mapping_a = cls.env["cc.telephony.mapping"].search(
            [("campaign_id", "=", cls.campaign_a.id)], limit=1
        )
        if not cls.mapping_a:
            cls.env["cc.telephony.mapping"]._load_controlled_catalog()
            cls.mapping_a = cls.env["cc.telephony.mapping"].search(
                [("campaign_id", "=", cls.campaign_a.id)], limit=1
            )
        cls.requester = cls._create_user(
            "Quality Configuration Author",
            "cc-quality-author@example.invalid",
            ["codestra_cc_security.group_cc_global_administrator"],
        )
        cls.approver = cls._create_user(
            "Quality Configuration Approver",
            "cc-quality-approver@example.invalid",
            ["codestra_cc_security.group_cc_global_administrator"],
        )
        cls.identity_service = cls._create_user(
            "Quality Identity Service",
            "cc-quality-identity@example.invalid",
            ["base.group_user", "codestra_identity_provisioning.group_provisioning_service"],
        )
        cls.recording_service = cls._create_user(
            "Recording Integration Service",
            "cc-recording-service@example.invalid",
            ["codestra_cc_recordings.group_cc_recording_service"],
        )
        cls.agent_a = cls._create_user(
            "Quality Agent A",
            "cc-quality-agent-a@example.invalid",
            ["codestra_cc_security.group_cc_campaign_agent"],
        )
        cls.agent_b = cls._create_user(
            "Quality Agent B",
            "cc-quality-agent-b@example.invalid",
            ["codestra_cc_security.group_cc_campaign_agent"],
        )
        cls.supervisor_a = cls._create_user(
            "Quality Supervisor A",
            "cc-quality-supervisor-a@example.invalid",
            ["codestra_cc_security.group_cc_campaign_supervisor"],
        )
        cls.qa_a = cls._create_user(
            "Quality Analyst A",
            "cc-quality-qa-a@example.invalid",
            ["codestra_cc_security.group_cc_quality_analyst"],
        )
        cls.qa_finalizer_a = cls._create_user(
            "Quality Finalizer A",
            "cc-quality-finalizer-a@example.invalid",
            ["codestra_cc_security.group_cc_quality_analyst"],
        )
        cls.qa_b = cls._create_user(
            "Quality Analyst B",
            "cc-quality-qa-b@example.invalid",
            ["codestra_cc_security.group_cc_quality_analyst"],
        )
        cls.compliance_a = cls._create_user(
            "Recording Compliance A",
            "cc-recording-compliance-a@example.invalid",
            ["codestra_cc_security.group_cc_compliance_officer"],
        )
        cls.agent_membership_a = cls._activate_membership(
            cls.agent_a, cls.campaign_a, "QUALITY-AGENT-A", "agent"
        )
        cls.agent_membership_b = cls._activate_membership(
            cls.agent_b, cls.campaign_b, "QUALITY-AGENT-B", "agent"
        )
        cls.supervisor_membership_a = cls._activate_membership(
            cls.supervisor_a,
            cls.campaign_a,
            "QUALITY-SUPERVISOR-A",
            "supervisor",
            is_primary_supervisor=True,
        )
        cls.qa_membership_a = cls._activate_membership(
            cls.qa_a, cls.campaign_a, "QUALITY-QA-A", "qa"
        )
        cls.qa_finalizer_membership_a = cls._activate_membership(
            cls.qa_finalizer_a, cls.campaign_a, "QUALITY-QA-FINAL-A", "qa"
        )
        cls.qa_membership_b = cls._activate_membership(
            cls.qa_b, cls.campaign_b, "QUALITY-QA-B", "qa"
        )
        cls.compliance_membership_a = cls._activate_membership(
            cls.compliance_a, cls.campaign_a, "QUALITY-COMPLIANCE-A", "compliance"
        )
        cls.partner_a = cls.env["res.partner"].create(
            {
                "name": "Synthetic Recording Customer A",
                "email": "recording-a@example.invalid",
                "phone": "+1 555 100 1001",
            }
        )
        cls.partner_b = cls.env["res.partner"].create(
            {
                "name": "Synthetic Recording Customer B",
                "email": "recording-b@example.invalid",
                "phone": "+1 555 200 2002",
            }
        )
        cls.profile_a = cls.env["cc.customer.profile"].with_user(cls.requester).create_from_partner(
            cls.partner_a, cls.campaign_a, "recording-profile-a"
        )
        cls.profile_b = cls.env["cc.customer.profile"].with_user(cls.requester).create_from_partner(
            cls.partner_b, cls.campaign_b, "recording-profile-b"
        )
        cls.profile_a.with_user(cls.requester).write({"assigned_user_id": cls.agent_a.id})
        cls.profile_b.with_user(cls.requester).write({"assigned_user_id": cls.agent_b.id})

        cls.legacy_campaign_a = cls.env["codestra.vicidial.campaign"].search(
            [("campaign_id", "=", cls.mapping_a.vicidial_campaign_id)], limit=1
        )
        if not cls.legacy_campaign_a:
            cls.legacy_campaign_a = cls.env["codestra.vicidial.campaign"].create(
                {
                    "name": "Synthetic Recording Campaign A",
                    "campaign_id": cls.mapping_a.vicidial_campaign_id,
                }
            )
        cls.legacy_agent_a = cls.env["codestra.vicidial.agent"].create(
            {
                "name": "Synthetic Recording Agent A",
                "vicidial_user": "CCRECQA001",
                "odoo_user_id": cls.agent_a.id,
            }
        )
        cls.legacy_call_a = cls.env["codestra.vicidial.call"].create(
            {
                "name": "Synthetic Canonical Recording Call A",
                "uniqueid": "cc-recording-call-a-001",
                "campaign_id": cls.legacy_campaign_a.id,
                "agent_id": cls.legacy_agent_a.id,
                "duration_seconds": 60,
                "billable_seconds": 55,
            }
        )
        cls.legacy_recording_a = cls.env["codestra.vicidial.recording"].create(
            {
                "recording_uid": "REC-" + "7" * 32,
                "vicidial_call_id": cls.legacy_call_a.uniqueid,
                "call_id": cls.legacy_call_a.id,
                "campaign_id": cls.legacy_campaign_a.id,
                "agent_id": cls.legacy_agent_a.id,
                "duration_seconds": 60,
                "format": "mp3",
                "file_size_bytes": 1024,
                "sha256": "8" * 64,
                "object_version_id": "synthetic-object-version-a-001",
                "storage_status": "odoo_linked",
                "verification_status": "verified",
                "retention_class": "synthetic_test",
                "environment": "staging",
            }
        )
        cls.recording_policy_a = cls.env["cc.recording.policy"].with_user(cls.requester).create(
            {
                "campaign_id": cls.campaign_a.id,
                "name": "Synthetic Recording Policy A",
                "version": 1,
                "source_reference": "TEST-RECORDING-POLICY-A",
                "retention_days": 30,
            }
        )
        cls.recording_policy_a.with_user(cls.requester).action_submit()
        cls.recording_policy_a.with_user(cls.approver).action_approve()
        cls.recording_policy_a.with_user(cls.approver).action_activate()
        cls.recording_a = cls.env["cc.recording"].with_user(cls.recording_service).bind_metadata(
            legacy_recording_id=cls.legacy_recording_a.id,
            campaign_id=cls.campaign_a.id,
            telephony_mapping_id=cls.mapping_a.id,
            agent_membership_id=cls.agent_membership_a.id,
            customer_profile_id=cls.profile_a.id,
            policy_id=cls.recording_policy_a.id,
            source_call_unique_id=cls.legacy_call_a.uniqueid,
        )

        cls.program_a = cls.env["cc.quality.program"].with_user(cls.requester).create(
            {
                "campaign_id": cls.campaign_a.id,
                "name": "Synthetic Quality Program A",
                "version": 1,
                "source_reference": "TEST-QUALITY-PROGRAM-A",
                "passing_score": 85.0,
                "critical_fail_score": 0.0,
            }
        )
        cls.question_critical = cls.env["cc.quality.question"].with_user(cls.requester).create(
            {
                "campaign_id": cls.campaign_a.id,
                "program_id": cls.program_a.id,
                "sequence": 10,
                "code": "DISCLOSURE",
                "text": "Required disclosure completed",
                "weight": 60,
                "maximum_points": 1.0,
                "critical_fail": True,
            }
        )
        cls.question_service = cls.env["cc.quality.question"].with_user(cls.requester).create(
            {
                "campaign_id": cls.campaign_a.id,
                "program_id": cls.program_a.id,
                "sequence": 20,
                "code": "SERVICE",
                "text": "Service quality met",
                "weight": 40,
                "maximum_points": 1.0,
            }
        )
        cls.program_a.with_user(cls.requester).action_submit()
        cls.program_a.with_user(cls.approver).action_approve()
        cls.program_a.with_user(cls.approver).action_activate()

    @classmethod
    def _create_user(cls, name, login, group_xmlids):
        groups = cls.env["res.groups"].browse([cls.env.ref(xmlid).id for xmlid in group_xmlids])
        return cls.env["res.users"].create(
            {"name": name, "login": login, "group_ids": [(6, 0, groups.ids)]}
        )

    @classmethod
    def _activate_membership(
        cls, user, campaign, ticket, role, is_primary_supervisor=False
    ):
        employee = cls.env["hr.employee"].create(
            {"name": user.name, "user_id": user.id, "company_id": cls.env.company.id}
        )
        membership = cls.env["cc.campaign.membership"].with_user(cls.requester).create(
            {
                "user_id": user.id,
                "employee_id": employee.id,
                "campaign_id": campaign.id,
                "role": role,
                "is_primary_supervisor": is_primary_supervisor,
                "requested_by_id": cls.requester.id,
                "source_ticket": ticket,
                "starts_at": fields.Datetime.now(),
            }
        )
        membership.with_user(cls.requester).action_submit_identity()
        operation = membership.with_user(cls.approver).action_approve_identity()
        operation.with_user(cls.identity_service).action_record_readback(
            {
                target: {"status": "matched", "evidence_hash": "a" * 64}
                for target in operation.required_targets
            },
            f"staging://quality/{ticket.lower()}",
        )
        membership.with_user(cls.approver).action_activate()
        return membership

    def _finalized_evaluation(self, critical_fail=False):
        sample = self.env["cc.quality.sample"].with_user(self.supervisor_a).assign_sample(
            program_id=self.program_a.id,
            recording_id=self.recording_a.id,
            assigned_qa_membership_id=self.qa_membership_a.id,
            sample_reason="risk" if critical_fail else "random",
            reason_reference="synthetic-risk" if critical_fail else "synthetic-random",
        )
        evaluation = self.env["cc.quality.evaluation"].with_user(self.qa_a).begin_for_sample(
            sample.with_user(self.qa_a)
        )
        evaluation.with_user(self.qa_a).set_answer(
            self.question_critical,
            0.0 if critical_fail else 1.0,
            "fail" if critical_fail else "pass",
            "Synthetic disclosure result",
        )
        evaluation.with_user(self.qa_a).set_answer(
            self.question_service, 1.0, "pass", "Synthetic service result"
        )
        evaluation.with_user(self.qa_a).action_submit()
        with self.assertRaises(ValidationError):
            evaluation.with_user(self.qa_a).action_finalize()
        evaluation.with_user(self.qa_finalizer_a).action_finalize()
        return sample, evaluation

    def test_recording_policy_binding_is_exact_idempotent_and_campaign_scoped(self):
        self.assertEqual(self.recording_a.campaign_id, self.campaign_a)
        self.assertEqual(self.recording_a.policy_hash, self.recording_policy_a.policy_hash)
        self.assertEqual(len(self.recording_a.storage_reference_hash), 64)
        repeated = self.env["cc.recording"].with_user(self.recording_service).bind_metadata(
            legacy_recording_id=self.legacy_recording_a.id,
            campaign_id=self.campaign_a.id,
            telephony_mapping_id=self.mapping_a.id,
            agent_membership_id=self.agent_membership_a.id,
            customer_profile_id=self.profile_a.id,
            policy_id=self.recording_policy_a.id,
            source_call_unique_id=self.legacy_call_a.uniqueid,
        )
        self.assertEqual(repeated, self.recording_a)
        with self.assertRaises(ValidationError):
            self.env["cc.recording"].with_user(self.recording_service).bind_metadata(
                legacy_recording_id=self.legacy_recording_a.id,
                campaign_id=self.campaign_a.id,
                telephony_mapping_id=self.mapping_a.id,
                agent_membership_id=self.agent_membership_a.id,
                customer_profile_id=self.profile_b.id,
                policy_id=self.recording_policy_a.id,
                source_call_unique_id=self.legacy_call_a.uniqueid,
            )
        with self.assertRaises(AccessError):
            self.env["cc.recording"].with_user(self.recording_service).create(
                {"campaign_id": self.campaign_a.id}
            )
        with self.assertRaises(AccessError):
            self.recording_a.with_user(self.agent_a).check_access("read")
        self.assertEqual(
            self.env["cc.recording"].with_user(self.qa_a).search([]), self.recording_a
        )
        self.assertFalse(self.env["cc.recording"].with_user(self.qa_b).search([]))

    def test_playback_and_ai_are_disabled_and_access_evidence_is_immutable(self):
        params = self.env["ir.config_parameter"]
        self.assertEqual(params.get_param("CC_ENABLE_RECORDING_PLAYBACK"), "false")
        self.assertEqual(params.get_param("CC_ENABLE_AI_ASSIST"), "false")
        result = self.recording_a.with_user(self.qa_a).action_request_playback(
            "quality_review"
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "recording_playback_disabled")
        event = self.env["cc.recording.access.event"].search(
            [("event_uuid", "=", result["event_id"])]
        )
        self.assertEqual(event.decision, "blocked")
        with self.assertRaises(AccessError):
            event.unlink()
        with self.assertRaises(UserError):
            self.legacy_recording_a.action_play_recording()

    def test_legal_hold_is_purpose_bound_hashed_and_reversible(self):
        self.recording_a.with_user(self.compliance_a).action_apply_legal_hold(
            "synthetic legal hold ticket"
        )
        self.assertTrue(self.recording_a.legal_hold)
        self.assertEqual(self.recording_a.storage_state, "legal_hold")
        event = self.recording_a.retention_event_ids
        self.assertEqual(event.event_type, "legal_hold_applied")
        self.assertEqual(len(event.reason_hash), 64)
        with self.assertRaises(AccessError):
            self.recording_a.with_user(self.compliance_a).write({"legal_hold": False})
        self.recording_a.with_user(self.compliance_a).action_release_legal_hold(
            "synthetic legal hold release ticket"
        )
        self.assertFalse(self.recording_a.legal_hold)
        self.assertEqual(len(self.recording_a.retention_event_ids), 2)

    def test_quality_program_is_separately_approved_versioned_and_immutable(self):
        self.assertEqual(self.program_a.state, "active")
        self.assertEqual(sum(self.program_a.question_ids.mapped("weight")), 100)
        self.assertEqual(len(self.program_a.program_hash), 64)
        self.assertNotEqual(self.program_a.requested_by_id, self.program_a.approved_by_id)
        with self.assertRaises(AccessError):
            self.question_service.with_user(self.requester).write({"weight": 30})
        invalid = self.env["cc.quality.program"].with_user(self.requester).create(
            {
                "campaign_id": self.campaign_a.id,
                "name": "Invalid Weight Program",
                "version": 2,
                "source_reference": "TEST-QUALITY-PROGRAM-A-V2",
            }
        )
        self.env["cc.quality.question"].with_user(self.requester).create(
            {
                "campaign_id": self.campaign_a.id,
                "program_id": invalid.id,
                "code": "INCOMPLETE",
                "text": "Incomplete weight",
                "weight": 90,
            }
        )
        with self.assertRaises(ValidationError):
            invalid.with_user(self.requester).action_submit()

    def test_evaluation_requires_separate_finalizer_and_agent_acknowledgement(self):
        sample, evaluation = self._finalized_evaluation()
        self.assertEqual(sample.state, "evaluated")
        self.assertEqual(evaluation.state, "finalized")
        self.assertEqual(evaluation.score, 100.0)
        self.assertFalse(evaluation.critical_failed)
        self.assertNotEqual(
            evaluation.evaluator_membership_id, evaluation.finalizer_membership_id
        )
        self.assertEqual(
            self.env["cc.quality.evaluation"].with_user(self.agent_a).search([]),
            evaluation,
        )
        self.assertFalse(
            self.env["cc.quality.evaluation"].with_user(self.agent_b).search([])
        )
        evaluation.with_user(self.agent_a).action_acknowledge()
        acknowledgement = self.env["cc.quality.event"].search(
            [("event_type", "=", "evaluation_acknowledged")]
        )
        self.assertEqual(acknowledgement.subject_membership_id, self.agent_membership_a)
        with self.assertRaises(AccessError):
            evaluation.with_user(self.qa_a).write({"score": 99.0})

    def test_critical_fail_and_correction_create_a_superseding_version(self):
        _sample, evaluation = self._finalized_evaluation(critical_fail=True)
        self.assertTrue(evaluation.critical_failed)
        self.assertEqual(evaluation.score, 0.0)
        correction = evaluation.with_user(self.qa_a).action_create_correction(
            "synthetic scoring correction"
        )
        self.assertEqual(correction.version, 2)
        self.assertEqual(correction.supersedes_id, evaluation)
        correction.with_user(self.qa_a).set_answer(
            self.question_critical, 1.0, "pass", "Corrected disclosure evidence"
        )
        correction.with_user(self.qa_a).action_submit()
        correction.with_user(self.qa_finalizer_a).action_finalize()
        self.assertEqual(correction.score, 100.0)
        self.assertEqual(evaluation.state, "finalized")

    def test_dispute_and_coaching_are_campaign_owned_and_evidenced(self):
        _sample, evaluation = self._finalized_evaluation()
        dispute = evaluation.with_user(self.agent_a).action_open_dispute(
            "synthetic evaluation dispute"
        )
        with self.assertRaises(ValidationError):
            dispute.with_user(self.qa_a).action_resolve(
                "upheld", "author cannot resolve"
            )
        dispute.with_user(self.qa_finalizer_a).action_resolve(
            "upheld", "independent synthetic resolution"
        )
        self.assertEqual(dispute.state, "upheld")
        plan = self.env["cc.coaching.plan"].with_user(
            self.supervisor_a
        ).create_for_evaluation(
            evaluation.with_user(self.supervisor_a),
            "Review the approved disclosure workflow",
            fields.Datetime.now() + timedelta(days=7),
        )
        self.assertFalse(plan.recording_sample_allowed)
        plan.with_user(self.agent_a).action_acknowledge()
        plan.with_user(self.supervisor_a).action_complete(
            "synthetic coaching completion evidence"
        )
        plan.with_user(self.supervisor_a).action_review_effectiveness(
            "effective", "synthetic effectiveness evidence"
        )
        self.assertEqual(plan.state, "effectiveness_reviewed")
        self.assertEqual(len(plan.completion_evidence_hash), 64)
        self.assertFalse(self.env["cc.coaching.plan"].with_user(self.agent_b).search([]))

    def test_calibration_is_version_bound_and_cross_campaign_assignment_fails(self):
        _sample, evaluation = self._finalized_evaluation()
        calibration = self.env["cc.quality.calibration"].with_user(
            self.supervisor_a
        ).schedule_calibration(
            self.program_a.with_user(self.supervisor_a),
            evaluation.with_user(self.supervisor_a),
            fields.Datetime.now(),
        )
        calibration.with_user(self.supervisor_a).action_complete()
        self.assertEqual(calibration.state, "completed")
        self.assertEqual(calibration.variance, 0.0)
        self.assertEqual(len(calibration.outcome_hash), 64)
        with self.assertRaises(Exception) as caught:
            self.env["cc.quality.sample"].with_user(self.supervisor_a).assign_sample(
                program_id=self.program_a.id,
                recording_id=self.recording_a.id,
                assigned_qa_membership_id=self.qa_membership_b.id,
                sample_reason="risk",
                reason_reference="synthetic-cross-campaign",
            )
        self.assertIsInstance(caught.exception, (AccessError, ValidationError))
