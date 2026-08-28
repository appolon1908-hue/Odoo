from datetime import datetime, timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..models.guards import contains_prohibited_payment_data


@tagged("post_install", "-at_install")
class TestCampaignComplianceWorkflow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["cc.business.unit"]._adopt_legacy_records()
        cls.Campaign = cls.env["cc.campaign"].with_context(active_test=False)
        cls.campaign_a = cls.Campaign.search([("code", "=", "COD-WEB-OUT")], limit=1)
        cls.campaign_b = cls.Campaign.search([("id", "!=", cls.campaign_a.id)], limit=1)
        if not cls.campaign_a or not cls.campaign_b:
            raise AssertionError("Synthetic compliance campaigns were not adopted")
        cls.author = cls._create_user(
            "Compliance Policy Author",
            "cc-compliance-author@example.invalid",
            ["codestra_cc_security.group_cc_campaign_configuration_manager"],
        )
        cls.global_admin = cls._create_user(
            "Compliance Global Approver",
            "cc-compliance-global@example.invalid",
            ["codestra_cc_security.group_cc_global_administrator"],
        )
        cls.membership_requester = cls._create_user(
            "Compliance Membership Requester",
            "cc-compliance-membership@example.invalid",
            ["codestra_cc_security.group_cc_global_administrator"],
        )
        cls.identity_service = cls._create_user(
            "Compliance Identity Service",
            "cc-compliance-identity@example.invalid",
            ["base.group_user", "codestra_identity_provisioning.group_provisioning_service"],
        )
        cls.crm_service = cls._create_user(
            "Compliance CRM Service",
            "cc-compliance-crm@example.invalid",
            ["codestra_cc_crm.group_cc_crm_service"],
        )
        cls.compliance_service = cls._create_user(
            "Compliance Event Service",
            "cc-compliance-service@example.invalid",
            ["codestra_cc_compliance.group_cc_compliance_event_service"],
        )
        cls.agent_a = cls._create_user(
            "Compliance Agent A",
            "cc-compliance-agent-a@example.invalid",
            ["codestra_cc_security.group_cc_campaign_agent"],
        )
        cls.agent_b = cls._create_user(
            "Compliance Agent B",
            "cc-compliance-agent-b@example.invalid",
            ["codestra_cc_security.group_cc_campaign_agent"],
        )
        cls.supervisor_a = cls._create_user(
            "Compliance Supervisor A",
            "cc-compliance-supervisor-a@example.invalid",
            ["codestra_cc_security.group_cc_campaign_supervisor"],
        )
        cls.compliance_a = cls._create_user(
            "Compliance Officer A",
            "cc-compliance-officer-a@example.invalid",
            ["codestra_cc_security.group_cc_compliance_officer"],
        )
        cls.compliance_b = cls._create_user(
            "Compliance Officer B",
            "cc-compliance-officer-b@example.invalid",
            ["codestra_cc_security.group_cc_compliance_officer"],
        )
        cls.author_membership = cls._activate_membership(
            cls.author, cls.campaign_a, "COMPLIANCE-CONFIG-A", "configuration_manager"
        )
        cls.agent_membership_a = cls._activate_membership(
            cls.agent_a, cls.campaign_a, "COMPLIANCE-AGENT-A", "agent"
        )
        cls.agent_membership_b = cls._activate_membership(
            cls.agent_b, cls.campaign_b, "COMPLIANCE-AGENT-B", "agent"
        )
        cls.supervisor_membership_a = cls._activate_membership(
            cls.supervisor_a,
            cls.campaign_a,
            "COMPLIANCE-SUPERVISOR-A",
            "supervisor",
            is_primary_supervisor=True,
        )
        cls.compliance_membership_a = cls._activate_membership(
            cls.compliance_a, cls.campaign_a, "COMPLIANCE-OFFICER-A", "compliance"
        )
        cls.compliance_membership_b = cls._activate_membership(
            cls.compliance_b, cls.campaign_b, "COMPLIANCE-OFFICER-B", "compliance"
        )
        partner_a = cls.env["res.partner"].create(
            {
                "name": "Synthetic Compliance Customer A",
                "phone": "+18095550123",
                "email": "customer-a@example.invalid",
            }
        )
        partner_b = cls.env["res.partner"].create(
            {
                "name": "Synthetic Compliance Customer B",
                "phone": "+18095550999",
                "email": "customer-b@example.invalid",
            }
        )
        cls.profile_a = cls.env["cc.customer.profile"].with_user(
            cls.crm_service
        ).create_from_partner(partner_a, cls.campaign_a, "COMPLIANCE-PROFILE-A")
        cls.profile_b = cls.env["cc.customer.profile"].with_user(
            cls.crm_service
        ).create_from_partner(partner_b, cls.campaign_b, "COMPLIANCE-PROFILE-B")
        cls.profile_a.with_user(cls.global_admin).write(
            {"assigned_user_id": cls.agent_a.id, "contact_timezone": "America/La_Paz"}
        )
        cls.profile_b.with_user(cls.global_admin).write(
            {"assigned_user_id": cls.agent_b.id, "contact_timezone": "UTC"}
        )
        cls.policy_a = cls.env["cc.compliance.policy"].with_user(cls.author).create(
            {
                "campaign_id": cls.campaign_a.id,
                "name": "Synthetic Phone Compliance Policy",
                "version": 1,
                "jurisdiction_code": "bo-test",
                "channel": "phone",
                "source_reference": "LEGAL-STAGING-COMPLIANCE-A",
                "consent_text_version": "CONSENT-PHONE-V1",
                "allowed_weekdays": [0, 1, 2, 3, 4, 5, 6],
                "calling_hour_start": 8.0,
                "calling_hour_end": 18.0,
            }
        )
        cls.policy_a.with_user(cls.author).action_submit()
        cls.policy_a.with_user(cls.global_admin).action_approve()
        cls.policy_a.with_user(cls.global_admin).action_activate()
        cls.lead_a = cls.env["crm.lead"].with_user(cls.crm_service).create(
            {
                "name": "Synthetic Governed Call Lead",
                "campaign_id": cls.campaign_a.id,
                "cc_customer_profile_id": cls.profile_a.id,
                "cc_contact_center_record": True,
                "cc_source_list_key": "COMPLIANCE-SYNTHETIC-LIST",
                "phone": "+18095550123",
                "user_id": cls.agent_a.id,
            }
        )

    @classmethod
    def _create_user(cls, name, login, group_xmlids):
        groups = cls.env["res.groups"].browse(
            [cls.env.ref(xmlid).id for xmlid in group_xmlids]
        )
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
        membership = cls.env["cc.campaign.membership"].with_user(
            cls.membership_requester
        ).create(
            {
                "user_id": user.id,
                "employee_id": employee.id,
                "campaign_id": campaign.id,
                "role": role,
                "is_primary_supervisor": is_primary_supervisor,
                "requested_by_id": cls.membership_requester.id,
                "source_ticket": ticket,
                "starts_at": fields.Datetime.now(),
            }
        )
        membership.with_user(cls.membership_requester).action_submit_identity()
        operation = membership.with_user(cls.global_admin).action_approve_identity()
        operation.with_user(cls.identity_service).action_record_readback(
            {
                target: {"status": "matched", "evidence_hash": "a" * 64}
                for target in operation.required_targets
            },
            f"staging://compliance/{ticket.lower()}",
        )
        membership.with_user(cls.global_admin).action_activate()
        return membership

    def _grant_consent(self, suffix="001"):
        return self.env["cc.consent.evidence"].with_user(self.agent_a).record_consent(
            customer_profile=self.profile_a,
            channel="phone",
            destination="+18095550123",
            consent_source="synthetic-agent-disclosure",
            consent_text_version="CONSENT-PHONE-V1",
            evidence_reference=f"staging://consent/{suffix}",
            source_payload_hash="b" * 64,
            idempotency_key=f"consent-grant-{suffix}",
        )

    def test_policy_is_versioned_separately_approved_and_fail_closed(self):
        self.assertEqual(self.policy_a.state, "active")
        self.assertEqual(self.policy_a.jurisdiction_code, "BO-TEST")
        self.assertNotEqual(self.policy_a.author_id, self.policy_a.approver_id)
        self.assertEqual(len(self.policy_a.policy_hash), 64)
        self.assertFalse(self.policy_a.predictive_dialing_allowed)
        self.assertFalse(self.policy_a.ai_voice_allowed)
        self.assertFalse(self.policy_a.direct_payment_capture_allowed)
        with self.assertRaises(AccessError):
            self.policy_a.with_user(self.author).write({"calling_hour_end": 23.0})
        with self.assertRaises(ValidationError):
            self.env["cc.compliance.policy"].with_user(self.author).create(
                {
                    "campaign_id": self.campaign_a.id,
                    "name": "Unsafe Draft",
                    "version": 2,
                    "jurisdiction_code": "BO-TEST",
                    "channel": "email",
                    "source_reference": "UNSAFE-STAGING-DRAFT",
                    "consent_text_version": "EMAIL-V1",
                    "predictive_dialing_allowed": True,
                }
            )

    def test_consent_is_idempotent_and_revocation_immediately_suppresses(self):
        consent = self._grant_consent("REVOCATION")
        replay = self._grant_consent("REVOCATION")
        self.assertEqual(consent, replay)
        revocation = self.env["cc.consent.evidence"].with_user(
            self.agent_a
        ).record_revocation(
            consent=consent,
            destination="+18095550123",
            source="customer_verbal_revocation",
            evidence_reference="staging://consent/revocation",
            source_payload_hash="c" * 64,
            idempotency_key="consent-revocation-001",
        )
        self.assertEqual(revocation.status, "revoked")
        suppression = self.env["cc.suppression.entry"].with_user(self.agent_a).search(
            [("customer_profile_id", "=", self.profile_a.id), ("state", "=", "active")]
        )
        self.assertEqual(len(suppression), 1)
        decision = self.env["cc.contact.eligibility.evidence"].with_user(
            self.agent_a
        )._evaluate_at(
            customer_profile=self.profile_a,
            channel="phone",
            destination="+18095550123",
            idempotency_key="eligibility-after-revocation-001",
            dial_mode="manual",
            voice_mode="human",
            evaluated_at=datetime(2026, 8, 28, 16, 0, 0),
        )
        self.assertEqual(decision.result, "blocked_dnc")

    def test_calling_hours_use_protected_customer_local_timezone(self):
        self._grant_consent("CALLING-HOURS")
        inside = self.env["cc.contact.eligibility.evidence"].with_user(
            self.agent_a
        )._evaluate_at(
            customer_profile=self.profile_a,
            channel="phone",
            destination="+18095550123",
            idempotency_key="eligibility-local-inside-001",
            dial_mode="manual",
            voice_mode="human",
            evaluated_at=datetime(2026, 8, 28, 16, 0, 0),
        )
        outside = self.env["cc.contact.eligibility.evidence"].with_user(
            self.agent_a
        )._evaluate_at(
            customer_profile=self.profile_a,
            channel="phone",
            destination="+18095550123",
            idempotency_key="eligibility-local-outside-001",
            dial_mode="manual",
            voice_mode="human",
            evaluated_at=datetime(2026, 8, 29, 3, 0, 0),
        )
        self.assertEqual(inside.customer_timezone, "America/La_Paz")
        self.assertEqual(inside.customer_local_minute, 12 * 60)
        self.assertEqual(inside.result, "eligible")
        self.assertEqual(outside.customer_local_minute, 23 * 60)
        self.assertEqual(outside.result, "outside_hours")

    def test_predictive_and_ai_voice_remain_blocked(self):
        self._grant_consent("CAPABILITIES")
        predictive = self.env["cc.contact.eligibility.evidence"].with_user(
            self.agent_a
        )._evaluate_at(
            customer_profile=self.profile_a,
            channel="phone",
            destination="+18095550123",
            idempotency_key="eligibility-predictive-001",
            dial_mode="predictive",
            voice_mode="human",
            evaluated_at=datetime(2026, 8, 28, 16, 0, 0),
        )
        ai_voice = self.env["cc.contact.eligibility.evidence"].with_user(
            self.agent_a
        )._evaluate_at(
            customer_profile=self.profile_a,
            channel="phone",
            destination="+18095550123",
            idempotency_key="eligibility-ai-voice-001",
            dial_mode="manual",
            voice_mode="ai",
            evaluated_at=datetime(2026, 8, 28, 16, 0, 0),
        )
        self.assertEqual(predictive.result, "blocked_capability")
        self.assertEqual(ai_voice.result, "blocked_capability")

    def test_dnc_blocks_click_to_call_before_agent_or_middleware_lookup(self):
        suppression = self.env["cc.suppression.entry"].with_user(
            self.agent_a
        ).record_suppression(
            customer_profile=self.profile_a,
            identifier_type="phone",
            identifier="+18095550123",
            reason="dnc",
            source_reference="staging://customer/dnc",
            idempotency_key="dnc-before-next-call-001",
        )
        self.assertEqual(suppression.state, "active")
        with self.assertRaisesRegex(UserError, "blocked_dnc"):
            self.lead_a.with_user(self.agent_a).action_click_to_call()

    def test_dnc_removal_requires_separate_approval(self):
        entry = self.env["cc.suppression.entry"].with_user(
            self.compliance_a
        ).record_suppression(
            customer_profile=self.profile_a,
            identifier_type="phone",
            identifier="+18095550123",
            reason="dnc",
            source_reference="staging://customer/dnc-review",
            idempotency_key="dnc-release-review-001",
        )
        entry.with_user(self.compliance_a).action_request_release(
            reason="Synthetic verified correction", source_ticket="LEGAL-CHANGE-001"
        )
        with self.assertRaises(AccessError):
            entry.with_user(self.compliance_a).action_approve_release()
        entry.with_user(self.global_admin).action_approve_release()
        self.assertEqual(entry.state, "released")
        self.assertEqual(len(entry.release_evidence_hash), 64)

    def test_payment_workflow_requires_pause_and_stores_only_hashes(self):
        session = self.env["cc.payment.safety.session"].with_user(
            self.agent_a
        ).begin_session(
            policy=self.policy_a,
            customer_profile=self.profile_a,
            call_unique_id="synthetic-payment-call-001",
            idempotency_key="payment-session-001",
        )
        self.assertEqual(session.state, "pause_required")
        with self.assertRaises(ValidationError):
            session.with_user(self.compliance_service).action_record_tokenized_handoff(
                provider_reference_hash="d" * 64,
                tokenization_evidence_hash="e" * 64,
            )
        session.with_user(self.compliance_service).action_record_pause(
            evidence_reference="staging://recording/pause/001"
        )
        session.with_user(self.compliance_service).action_record_tokenized_handoff(
            provider_reference_hash="d" * 64,
            tokenization_evidence_hash="e" * 64,
        )
        session.with_user(self.compliance_service).action_complete(
            evidence_reference="staging://payment/completion/001"
        )
        self.assertEqual(session.state, "completed")
        self.assertEqual(len(session.final_evidence_hash), 64)
        self.assertEqual(
            session.event_ids.mapped("event_type"),
            ["pause_required", "paused", "tokenized_handoff", "completed"],
        )
        self.assertFalse(
            {"card_number", "cvv", "bank_account", "payment_url"}.intersection(
                session._fields
            )
        )
        with self.assertRaises(AccessError):
            self.env["cc.payment.safety.session"].with_user(self.agent_a).create(
                {
                    "campaign_id": self.campaign_a.id,
                    "payment_uuid": "forged",
                    "idempotency_key": "forged",
                    "policy_id": self.policy_a.id,
                    "customer_profile_id": self.profile_a.id,
                    "agent_membership_id": self.agent_membership_a.id,
                    "call_unique_id": "forged",
                    "requested_by_id": self.agent_a.id,
                }
            )

    def test_payment_data_is_rejected_from_notes_and_chatter(self):
        self.assertTrue(contains_prohibited_payment_data("4111 1111 1111 1111"))
        self.assertTrue(contains_prohibited_payment_data("CVV: 123"))
        self.assertFalse(contains_prohibited_payment_data("tokenized provider reference"))
        with self.assertRaises(ValidationError):
            self.lead_a.with_user(self.global_admin).write(
                {"description": "Customer card 4111 1111 1111 1111"}
            )
        with self.assertRaises(ValidationError):
            self.env["mail.message"].with_user(self.global_admin).create(
                {
                    "model": "crm.lead",
                    "res_id": self.lead_a.id,
                    "message_type": "comment",
                    "body": "Bank account: 123456789",
                }
            )

    def test_legal_hold_blocks_retention_even_after_policy_date(self):
        hold = self.env["cc.legal.hold"].with_user(self.compliance_a).request_hold(
            policy=self.policy_a,
            target_model="crm.lead",
            target_reference=self.lead_a.id,
            reason="Synthetic litigation preservation",
            source_ticket="LEGAL-HOLD-001",
            idempotency_key="legal-hold-001",
        )
        with self.assertRaises(AccessError):
            hold.with_user(self.compliance_a).action_activate()
        hold.with_user(self.global_admin).action_activate()
        decision = self.env["cc.retention.decision"].with_user(
            self.global_admin
        ).assess_retention(
            policy=self.policy_a,
            target_model="crm.lead",
            target_reference=self.lead_a.id,
            record_created_at=fields.Datetime.now() - timedelta(days=1000),
            idempotency_key="retention-held-001",
        )
        self.assertEqual(decision.outcome, "legal_hold")
        self.assertEqual(decision.legal_hold_id, hold)
        hold.with_user(self.global_admin).action_release(
            reason="Synthetic legal release approved"
        )
        self.assertEqual(hold.state, "released")

    def test_cross_campaign_evidence_and_live_flags_are_closed(self):
        entry = self.env["cc.suppression.entry"].with_user(
            self.agent_a
        ).record_suppression(
            customer_profile=self.profile_a,
            identifier_type="phone",
            identifier="+18095550123",
            reason="dnc",
            source_reference="staging://scope/dnc",
            idempotency_key="dnc-scope-001",
        )
        self.assertFalse(
            self.env["cc.suppression.entry"].with_user(self.agent_b).search(
                [("id", "=", entry.id)]
            )
        )
        params = self.env["ir.config_parameter"]
        for key in (
            "CC_ENABLE_AUTOMATED_OUTREACH",
            "CC_ENABLE_PREDICTIVE_DIALING",
            "CC_ENABLE_PRERECORDED_VOICE",
            "CC_ENABLE_PAYMENT_DELIVERY",
        ):
            self.assertEqual(params.get_param(key), "false")

    def test_direct_consent_forgery_is_denied(self):
        with self.assertRaises(AccessError):
            self.env["cc.consent.evidence"].with_user(self.agent_a).create(
                {
                    "campaign_id": self.campaign_a.id,
                    "event_uuid": "forged-consent",
                    "idempotency_key": "forged-consent",
                    "policy_id": self.policy_a.id,
                    "customer_profile_id": self.profile_a.id,
                    "channel": "phone",
                    "status": "granted",
                    "consent_source": "forged",
                    "consent_text_version": "CONSENT-PHONE-V1",
                    "destination_hash": "a" * 64,
                    "evidence_reference_hash": "b" * 64,
                    "source_payload_hash": "c" * 64,
                    "actor_id": self.agent_a.id,
                    "evidence_hash": "d" * 64,
                }
            )
