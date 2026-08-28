from datetime import datetime, timedelta, timezone
from pathlib import Path

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestCampaignCallOperations(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["cc.business.unit"]._adopt_legacy_records()
        cls.Campaign = cls.env["cc.campaign"].with_context(active_test=False)
        cls.campaign_a = cls.Campaign.search([("code", "=", "COD-WEB-OUT")], limit=1)
        cls.campaign_b = cls.Campaign.search(
            [("id", "!=", cls.campaign_a.id), ("channel_ids", "!=", False)], limit=1
        )
        cls.requester = cls._create_user(
            "Call Operations Requester",
            "cc-call-requester@example.invalid",
            ["codestra_cc_security.group_cc_global_administrator"],
        )
        cls.approver = cls._create_user(
            "Call Operations Approver",
            "cc-call-approver@example.invalid",
            ["codestra_cc_security.group_cc_global_administrator"],
        )
        cls.identity_service = cls._create_user(
            "Call Identity Service",
            "cc-call-identity@example.invalid",
            [
                "base.group_user",
                "codestra_identity_provisioning.group_provisioning_service",
                "codestra_cc_crm.group_cc_crm_service",
            ],
        )
        cls.call_service = cls._create_user(
            "Call Integration Service",
            "cc-call-service@example.invalid",
            ["base.group_user", "codestra_cc_calls.group_cc_call_service"],
        )
        cls.supervisor_a = cls._create_user(
            "Call Supervisor A",
            "cc-call-supervisor-a@example.invalid",
            ["codestra_cc_security.group_cc_campaign_supervisor"],
        )
        cls.supervisor_b = cls._create_user(
            "Call Supervisor B",
            "cc-call-supervisor-b@example.invalid",
            ["codestra_cc_security.group_cc_campaign_supervisor"],
        )
        cls.agent_a = cls._create_user(
            "Call Agent A",
            "cc-call-agent-a@example.invalid",
            ["codestra_cc_security.group_cc_campaign_agent"],
        )
        cls.agent_b = cls._create_user(
            "Call Agent B",
            "cc-call-agent-b@example.invalid",
            ["codestra_cc_security.group_cc_campaign_agent"],
        )
        cls.supervisor_membership_a = cls._activate_membership(
            cls.supervisor_a, cls.campaign_a, "CALL-SUPERVISOR-A", role="supervisor"
        )
        cls.supervisor_membership_b = cls._activate_membership(
            cls.supervisor_b, cls.campaign_b, "CALL-SUPERVISOR-B", role="supervisor"
        )
        cls.agent_membership_a = cls._activate_membership(
            cls.agent_a, cls.campaign_a, "CALL-AGENT-A"
        )
        cls.agent_membership_b = cls._activate_membership(
            cls.agent_b, cls.campaign_b, "CALL-AGENT-B"
        )
        cls.partner_a = cls.env["res.partner"].create(
            {"name": "Synthetic Call Customer A", "email": "call-a@example.invalid", "phone": "+1 555 010 1001"}
        )
        cls.partner_b = cls.env["res.partner"].create(
            {"name": "Synthetic Call Customer B", "email": "call-b@example.invalid", "phone": "+1 555 010 2002"}
        )
        cls.profile_a = cls.env["cc.customer.profile"].with_user(cls.requester).create_from_partner(
            cls.partner_a, cls.campaign_a, "cc-call-profile-a"
        )
        cls.profile_b = cls.env["cc.customer.profile"].with_user(cls.requester).create_from_partner(
            cls.partner_b, cls.campaign_b, "cc-call-profile-b"
        )
        cls.profile_a.with_user(cls.requester).write({"assigned_user_id": cls.agent_a.id})
        cls.profile_b.with_user(cls.requester).write({"assigned_user_id": cls.agent_b.id})
        cls.policy_a = cls.env["cc.callback.policy"].with_user(cls.requester).create(
            {
                "campaign_id": cls.campaign_a.id,
                "name": "Synthetic Campaign A Calling Hours",
                "timezone": "UTC",
                "allowed_weekdays": [0, 1, 2, 3, 4, 5, 6],
                "calling_hour_start": 0.0,
                "calling_hour_end": 24.0,
                "reminder_minutes": 15,
                "active": True,
            }
        )
        cls.policy_b = cls.env["cc.callback.policy"].with_user(cls.requester).create(
            {
                "campaign_id": cls.campaign_b.id,
                "name": "Synthetic Campaign B Calling Hours",
                "timezone": "UTC",
                "allowed_weekdays": [0, 1, 2, 3, 4, 5, 6],
                "calling_hour_start": 0.0,
                "calling_hour_end": 24.0,
                "reminder_minutes": 15,
                "active": True,
            }
        )
        cls.script_a, cls.script_version_a = cls._create_approved_script(
            cls.campaign_a, "Synthetic Transfer Script A", "CALL-SCRIPT-A"
        )
        cls.script_b, cls.script_version_b = cls._create_approved_script(
            cls.campaign_b, "Synthetic Transfer Script B", "CALL-SCRIPT-B"
        )
        cls.transfer_route_a = cls.env["cc.transfer.route"].with_user(cls.requester).create(
            {
                "campaign_id": cls.campaign_a.id,
                "name": "Campaign A Supervisor",
                "route_code": "SUPERVISOR",
                "destination_type": "supervisor",
                "destination_code": "SUPERVISOR",
                "destination_membership_id": cls.supervisor_membership_a.id,
                "transfer_type": "warm",
                "active": True,
            }
        )
        cls.transfer_route_b = cls.env["cc.transfer.route"].with_user(cls.requester).create(
            {
                "campaign_id": cls.campaign_b.id,
                "name": "Campaign B Supervisor",
                "route_code": "SUPERVISOR",
                "destination_type": "supervisor",
                "destination_code": "SUPERVISOR",
                "destination_membership_id": cls.supervisor_membership_b.id,
                "transfer_type": "warm",
                "active": True,
            }
        )
        cls.referral_route_a = cls.env["cc.referral.route"].with_user(cls.requester).create(
            {
                "campaign_id": cls.campaign_a.id,
                "service_code": "CAMPAIGN-B-SERVICE",
                "service_label": "Campaign B Requested Service",
                "destination_campaign_id": cls.campaign_b.id,
                "allowed_payload_keys": ["customer_name", "phone_masked", "request_summary"],
                "active": True,
            }
        )

    @classmethod
    def _create_user(cls, name, login, group_xmlids):
        groups = cls.env["res.groups"].browse([cls.env.ref(xmlid).id for xmlid in group_xmlids])
        return cls.env["res.users"].create(
            {"name": name, "login": login, "group_ids": [(6, 0, groups.ids)]}
        )

    @classmethod
    def _activate_membership(cls, user, campaign, ticket, role="agent"):
        employee = cls.env["hr.employee"].create(
            {"name": user.name, "user_id": user.id, "company_id": cls.env.company.id}
        )
        membership = cls.env["cc.campaign.membership"].with_user(cls.requester).create(
            {
                "user_id": user.id,
                "employee_id": employee.id,
                "campaign_id": campaign.id,
                "role": role,
                "is_primary_supervisor": role == "supervisor",
                "requested_by_id": cls.requester.id,
                "source_ticket": ticket,
                "starts_at": fields.Datetime.now(),
            }
        )
        membership.with_user(cls.requester).action_submit_identity()
        operation = membership.with_user(cls.approver).action_approve_identity()
        operation.with_user(cls.identity_service).action_record_readback(
            {target: {"status": "matched", "evidence_hash": "a" * 64} for target in operation.required_targets},
            f"staging://calls/{ticket.lower()}",
        )
        membership.with_user(cls.approver).action_activate()
        return membership

    @classmethod
    def _script_content(cls, marker):
        return {
            "opening": f"<p>{marker} identity</p>",
            "identity_verification": "<p>Verify the customer.</p>",
            "recording_disclosure": "<p>Provide disclosure.</p>",
            "qualification_questions": "<p>Ask approved questions.</p>",
            "product_explanation": "<p>Explain approved service.</p>",
            "objection_handling": "<p>Use approved guidance.</p>",
            "closing": "<p>Confirm the next step.</p>",
            "required_legal_statements": "<p>Read legal statements.</p>",
            "opt_out_language": "<p>Honor opt-out.</p>",
            "escalation_instructions": "<p>Escalate inside campaign.</p>",
            "prohibited_statements": "<p>Internal only.</p>",
            "supervisor_notes": "<p>Supervisor only.</p>",
        }

    @classmethod
    def _create_approved_script(cls, campaign, name, ticket):
        script = cls.env["cc.script"].with_user(cls.requester).create(
            {"name": name, "campaign_id": campaign.id, "language_code": "en"}
        )
        version = script.with_user(cls.requester).action_create_version(cls._script_content(campaign.code))
        version.with_user(cls.requester).action_submit_for_review()
        version.with_user(cls.approver).action_approve(ticket)
        return script, version

    @classmethod
    def _scheduled_at(cls):
        return fields.Datetime.to_string(datetime.now(timezone.utc) + timedelta(hours=2))

    def _create_callback(self, user, campaign, profile, policy, key):
        return self.env["cc.callback"].with_user(user).create(
            {
                "campaign_id": campaign.id,
                "name": f"Synthetic {key}",
                "callback_type": "customer",
                "customer_profile_id": profile.id,
                "source_call_unique_id": f"CALL-{key}",
                "scheduled_at": self._scheduled_at(),
                "customer_timezone": "UTC",
                "reason": "Synthetic callback validation",
                "consent_state": "captured",
                "policy_id": policy.id,
                "middleware_idempotency_key": key,
                "correlation_id": f"correlation-{key}",
            }
        )

    def test_models_and_safe_defaults_are_installed(self):
        for model_name in (
            "cc.callback.policy", "cc.callback", "cc.callback.history", "cc.appointment",
            "cc.reminder", "cc.operation.outbox", "cc.transfer.route", "cc.transfer",
            "cc.transfer.event", "cc.referral.route", "cc.referral", "cc.referral.delivery",
        ):
            self.assertIn(model_name, self.env)
        self.assertFalse(self.policy_a.publication_enabled)
        self.assertFalse(self.transfer_route_a.live_control_enabled)
        self.assertFalse(self.referral_route_a.delivery_enabled)
        parameters = self.env["ir.config_parameter"]
        self.assertEqual(parameters.get_param("CC_ENABLE_CALLBACK_PUBLICATION"), "false")
        self.assertEqual(parameters.get_param("CC_ENABLE_WARM_TRANSFER"), "false")

    def test_callback_schedules_once_is_campaign_owned_and_publication_stays_held(self):
        callback = self._create_callback(
            self.agent_a, self.campaign_a, self.profile_a, self.policy_a, "callback-a-001"
        )
        callback.with_user(self.agent_a).action_schedule()
        self.assertEqual(callback.state, "scheduled")
        self.assertEqual(callback.assigned_membership_id, self.agent_membership_a)
        self.assertEqual(callback.supervisor_membership_id, self.supervisor_membership_a)
        self.assertEqual(callback.publication_state, "held")
        self.assertEqual(len(callback.history_ids), 1)
        self.assertEqual(len(callback.reminder_ids), 1)
        event = self.env["cc.operation.outbox"].with_user(self.agent_a).search(
            [("aggregate_uuid", "=", callback.operation_uuid)]
        )
        self.assertEqual(len(event), 1)
        self.assertEqual(event.delivery_state, "held")
        self.assertEqual(event.hold_reason, "callback_publication_disabled")
        repeated = self.env["cc.operation.outbox"].with_user(self.agent_a)._emit(
            callback.with_user(self.agent_a),
            event.event_type,
            callback.middleware_idempotency_key,
            callback.correlation_id,
            event.payload,
            event.hold_reason,
        )
        self.assertEqual(repeated, event)
        with self.assertRaises(UserError):
            callback.with_user(self.agent_a).action_publish()

    def test_callback_scope_lifecycle_readback_and_immutable_evidence(self):
        callback = self._create_callback(
            self.agent_a, self.campaign_a, self.profile_a, self.policy_a, "callback-a-002"
        )
        callback.with_user(self.agent_a).action_schedule()
        callback.with_user(self.agent_a).action_ready()
        callback.with_user(self.agent_a).action_mark_missed()
        callback.with_user(self.supervisor_a).action_recover()
        self.assertEqual(callback.state, "recovery")
        callback.with_user(self.call_service).action_record_readback(
            "staging://vicidial/callback-a-002", "callback-readback-a-002"
        )
        callback.with_user(self.call_service).action_record_readback(
            "staging://vicidial/callback-a-002", "callback-readback-a-002"
        )
        self.assertEqual(callback.publication_state, "readback_matched")
        with self.assertRaises(ValidationError):
            callback.with_user(self.call_service).action_record_readback(
                "staging://vicidial/conflict", "callback-readback-a-002"
            )
        with self.assertRaises(AccessError):
            callback.with_user(self.agent_a).write({"campaign_id": self.campaign_b.id})
        with self.assertRaises(AccessError):
            callback.history_ids[:1].with_user(self.agent_a).unlink()
        with self.assertRaises(UserError):
            callback.with_user(self.agent_a).export_data(["name"])
        with self.assertRaises(AccessError):
            self._create_callback(
                self.agent_a, self.campaign_b, self.profile_b, self.policy_b, "forged-callback-b"
            )

    def test_appointment_creates_same_campaign_callback_and_preparation_reminder(self):
        appointment = self.env["cc.appointment"].with_user(self.agent_a).create(
            {
                "campaign_id": self.campaign_a.id,
                "name": "Synthetic Customer Appointment",
                "customer_profile_id": self.profile_a.id,
                "policy_id": self.policy_a.id,
                "scheduled_start": self._scheduled_at(),
                "scheduled_end": fields.Datetime.to_string(
                    fields.Datetime.to_datetime(self._scheduled_at()) + timedelta(minutes=30)
                ),
                "customer_timezone": "UTC",
                "reason": "Synthetic appointment",
                "consent_state": "captured",
            }
        )
        appointment.with_user(self.agent_a).action_schedule()
        self.assertEqual(appointment.state, "scheduled")
        self.assertEqual(appointment.callback_id.campaign_id, self.campaign_a)
        self.assertEqual(appointment.callback_id.callback_type, "appointment")
        self.assertEqual(appointment.callback_id.appointment_id, appointment)
        self.assertEqual(len(appointment.reminder_ids), 1)
        self.assertEqual(appointment.reminder_ids.event_type, "appointment_prep")
        appointment.reminder_ids.with_user(self.agent_a).action_acknowledge()
        self.assertEqual(appointment.reminder_ids.state, "acknowledged")

    def test_same_campaign_transfer_validates_and_cross_campaign_transfer_rejects(self):
        transfer = self.env["cc.transfer"].with_user(self.agent_a).request_transfer(
            campaign_id=self.campaign_a.id,
            source_call_unique_id="CALL-TRANSFER-A-001",
            customer_profile_id=self.profile_a.id,
            script_version_id=self.script_version_a.id,
            route_id=self.transfer_route_a.id,
            compliance_state="allowed",
            idempotency_key="transfer-a-001",
            correlation_id="correlation-transfer-a-001",
        )
        self.assertEqual(transfer.state, "validated")
        self.assertEqual(transfer.campaign_id, self.campaign_a)
        self.assertEqual(transfer.destination_membership_id.campaign_id, self.campaign_a)
        self.assertEqual(transfer.event_ids.event_type, "cc.transfer.validated.v1")
        self.assertEqual(
            self.env["cc.operation.outbox"].with_user(self.agent_a).search_count(
                [("aggregate_uuid", "=", transfer.operation_uuid)]
            ),
            1,
        )
        repeated = self.env["cc.transfer"].with_user(self.agent_a).request_transfer(
            campaign_id=self.campaign_a.id,
            source_call_unique_id="CALL-TRANSFER-A-001",
            customer_profile_id=self.profile_a.id,
            script_version_id=self.script_version_a.id,
            route_id=self.transfer_route_a.id,
            compliance_state="allowed",
            idempotency_key="transfer-a-001",
            correlation_id="correlation-transfer-a-001",
        )
        self.assertEqual(repeated, transfer)
        with self.assertRaises(UserError):
            transfer.with_user(self.agent_a).action_live_transfer()

        rejected = self.env["cc.transfer"].with_user(self.agent_a).request_transfer(
            campaign_id=self.campaign_a.id,
            source_call_unique_id="CALL-TRANSFER-A-002",
            customer_profile_id=self.profile_a.id,
            script_version_id=self.script_version_a.id,
            route_id=self.transfer_route_a.id,
            compliance_state="allowed",
            idempotency_key="transfer-a-002",
            correlation_id="correlation-transfer-a-002",
            requested_target_campaign_id=self.campaign_b.id,
        )
        self.assertEqual(rejected.state, "rejected")
        self.assertEqual(rejected.rejection_code, "cross_campaign")
        self.assertEqual(rejected.safe_status, "Transfer unavailable for this call.")
        self.assertFalse(
            self.env["cc.operation.outbox"].with_user(self.agent_a).search(
                [("aggregate_uuid", "=", rejected.operation_uuid)]
            )
        )

    def test_transfer_result_is_exactly_once_and_direct_forgery_is_denied(self):
        transfer = self.env["cc.transfer"].with_user(self.agent_a).request_transfer(
            campaign_id=self.campaign_a.id,
            source_call_unique_id="CALL-TRANSFER-A-003",
            customer_profile_id=self.profile_a.id,
            script_version_id=self.script_version_a.id,
            route_id=self.transfer_route_a.id,
            compliance_state="allowed",
            idempotency_key="transfer-a-003",
            correlation_id="correlation-transfer-a-003",
        )
        transfer.with_user(self.call_service).action_record_result("transfer-result-a-003", "completed")
        transfer.with_user(self.call_service).action_record_result("transfer-result-a-003", "completed")
        self.assertEqual(transfer.state, "completed")
        self.assertEqual(len(transfer.event_ids), 2)
        with self.assertRaises(ValidationError):
            transfer.with_user(self.call_service).action_record_result("transfer-result-a-003", "failed")
        with self.assertRaises(AccessError):
            self.env["cc.transfer"].with_user(self.agent_a).with_context(
                _cc_transfer_write_capability=True
            ).create({})
        with self.assertRaises(AccessError):
            transfer.event_ids[:1].with_user(self.agent_a).unlink()

    def test_cross_campaign_referral_shares_minimum_data_without_source_access(self):
        payload = {
            "customer_name": "Synthetic Customer",
            "phone_masked": "***1001",
            "request_summary": "Customer requested the other service.",
        }
        referral = self.env["cc.referral"].with_user(self.agent_a).request_referral(
            campaign_id=self.campaign_a.id,
            customer_profile_id=self.profile_a.id,
            service_code="CAMPAIGN-B-SERVICE",
            consent_reference="synthetic-consent-a-001",
            minimal_payload=payload,
            idempotency_key="referral-a-001",
            correlation_id="correlation-referral-a-001",
        )
        self.assertEqual(referral.state, "pending")
        self.assertEqual(referral.destination_service_label, "Campaign B Requested Service")
        self.assertEqual(len(referral.payload_hash), 64)
        self.assertEqual(
            referral.with_user(self.agent_a).route_id.service_code,
            "CAMPAIGN-B-SERVICE",
        )
        with self.assertRaises(AccessError):
            referral.route_id.with_user(self.agent_a).read(["destination_campaign_id"])
        with self.assertRaises(AccessError):
            self.env["cc.referral.delivery"].with_user(self.agent_a).search([])
        delivery = referral.with_user(self.call_service).action_materialize_destination(
            payload, "referral-delivery-a-001"
        )
        repeated = referral.with_user(self.call_service).action_materialize_destination(
            payload, "referral-delivery-a-001"
        )
        self.assertEqual(repeated, delivery)
        self.assertEqual(delivery.campaign_id, self.campaign_b)
        self.assertEqual(delivery.minimal_payload, payload)
        self.assertEqual(referral.state, "destination_created")
        self.assertEqual(
            self.env["cc.referral.delivery"].with_user(self.supervisor_b).search([]), delivery
        )
        with self.assertRaises(ValidationError):
            self.env["cc.referral"].with_user(self.agent_a).request_referral(
                campaign_id=self.campaign_a.id,
                customer_profile_id=self.profile_a.id,
                service_code="CAMPAIGN-B-SERVICE",
                consent_reference="synthetic-consent-a-002",
                minimal_payload={"request_summary": "Unsafe", "card_number": "4111111111111111"},
                idempotency_key="referral-a-002",
                correlation_id="correlation-referral-a-002",
            )

    def test_popout_assets_use_canonical_models_and_preserve_click_to_call(self):
        addon_root = Path(__file__).resolve().parents[1]
        javascript = (addon_root / "static/src/js/call_workspace_popouts.js").read_text(encoding="utf-8")
        template = (addon_root / "static/src/xml/call_workspace_popouts.xml").read_text(encoding="utf-8")
        for model_name in ("cc.appointment", "cc.callback", "cc.reminder"):
            self.assertIn(model_name, javascript)
        for label in (
            "Open appointment calendar pop-out",
            "Open reminder pop-out",
            "Open callback scheduler pop-out",
            "Close scheduling pop-out",
        ):
            self.assertIn(label, template)
        self.assertIn("force: true", javascript)
        click_to_call = addon_root.parent / "codestra_vicidial_crm/static/src/js/call_popup.js"
        self.assertTrue(click_to_call.is_file())
        click_to_call_source = click_to_call.read_text(encoding="utf-8")
        self.assertIn("CodestraCallPopup", click_to_call_source)
        self.assertIn("/codestra/call-control/v1", click_to_call_source)
