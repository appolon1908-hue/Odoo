import uuid

from odoo import SUPERUSER_ID, fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..models.provisioning import IMMUTABLE_ASSIGNMENT_FIELDS


def _nested_keys(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield str(key).lower()
            yield from _nested_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _nested_keys(nested)


@tagged("post_install", "-at_install")
class TestCodestraAgentOnboarding(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.country = cls.env.ref("base.us", raise_if_not_found=False)
        if not cls.country:
            cls.country = cls.env["res.country"].search([], limit=1)

        cls.unit = cls.env["call.center.business.unit"].create(
            {
                "name": "Onboarding Test Unit",
                "code": "ONB",
                "company_id": cls.company.id,
            }
        )
        # Legacy creation already adopts one canonical wrapper.
        cls.canonical_unit = cls.env["cc.business.unit"].with_context(
            active_test=False
        ).search([("legacy_business_unit_id", "=", cls.unit.id)])
        cls.canonical_unit.ensure_one()

        cls.requester = cls._create_user(
            "Onboarding Requester",
            "onboarding.requester@example.invalid",
            [
                "base.group_user",
                "call_center_core.group_call_center_manager",
                "codestra_cc_security.group_cc_global_administrator",
                "codestra_identity_provisioning.group_provisioning_user",
            ],
        )
        cls.approver = cls._create_user(
            "Onboarding Approver",
            "onboarding.approver@example.invalid",
            [
                "base.group_user",
                "call_center_core.group_call_center_manager",
                "codestra_cc_security.group_cc_global_administrator",
                "codestra_identity_provisioning.group_provisioning_approver",
            ],
        )
        cls.identity_service = cls._create_user(
            "Onboarding Identity Service",
            "onboarding.identity.service@example.invalid",
            [
                "base.group_user",
                "codestra_identity_provisioning.group_provisioning_service",
                "codestra_identity_provisioning.group_provisioning_user",
            ],
        )
        cls.supervisor = cls._create_user(
            "Onboarding Supervisor",
            "onboarding.supervisor@example.invalid",
            [
                "base.group_user",
                "codestra_cc_security.group_cc_campaign_supervisor",
            ],
        )

        cls.branch = cls.env["call.center.branch"].create(
            {
                "name": "Onboarding Test Branch",
                "code": "ONB-BR",
                "company_id": cls.company.id,
                "country_id": cls.country.id,
                "business_unit_ids": [(6, 0, cls.unit.ids)],
                "timezone": "UTC",
            }
        )
        cls.department = cls.env["call.center.department"].create(
            {
                "name": "Onboarding Operations",
                "code": "ONB-OPS",
                "business_unit_id": cls.unit.id,
                "branch_id": cls.branch.id,
            }
        )
        cls.team = cls.env["call.center.team"].create(
            {
                "name": "Onboarding Agent Team",
                "code": "ONB-T1",
                "business_unit_id": cls.unit.id,
                "department_id": cls.department.id,
                "supervisor_ids": [(6, 0, cls.supervisor.ids)],
            }
        )
        cls.legacy_campaign = cls.env["call.center.campaign"].create(
            {
                "name": "Onboarding Campaign",
                "code": "ONB-AGENT-OUT",
                "business_unit_id": cls.unit.id,
                "state": "approved",
                "design_automation_enabled": False,
                "active": False,
                "direction": "outbound",
                "team_ids": [(6, 0, cls.team.ids)],
                "supervisor_ids": [(6, 0, cls.supervisor.ids)],
                "start_date": fields.Date.today(),
                "timezone": "UTC",
                "telephony_enabled": True,
                "vicidial_required": True,
                "vicidial_campaign_id": "ONB0001",
                "vicidial_user_group": "ONB_AGENT",
                "reconciliation_status": "synced_disabled",
            }
        )
        cls.campaign = cls.env["cc.campaign"].with_context(
            active_test=False
        ).search([("legacy_campaign_id", "=", cls.legacy_campaign.id)])
        cls.campaign.ensure_one()
        assert cls.campaign.cc_business_unit_id == cls.canonical_unit
        assert cls.campaign.lifecycle_state == "approved"
        # The request and approval identities use an explicit, active campaign
        # scope.  Global workflow roles authorize the actions; this narrow
        # auditor membership authorizes reads of the governed workspace without
        # relying on superuser mode or a record-rule bypass.
        for user, label in (
            (cls.requester, "Requester"),
            (cls.approver, "Approver"),
        ):
            employee = cls.env["hr.employee"].create(
                {
                    "name": f"Onboarding {label}",
                    "company_id": cls.company.id,
                    "user_id": user.id,
                }
            )
            membership = cls.env["cc.campaign.membership"].with_user(
                cls.requester
            ).create(
                {
                    "user_id": user.id,
                    "employee_id": employee.id,
                    "campaign_id": cls.campaign.id,
                    "role": "auditor",
                    "state": "draft",
                    "requested_by_id": cls.requester.id,
                    "source_ticket": "TEST-ONBOARDING-SCOPE",
                }
            )
            membership.with_user(cls.requester).action_submit_identity()
            operation = membership.with_user(cls.approver).action_approve_identity()
            operation.with_user(cls.identity_service).action_record_readback(
                {
                    target: {"status": "matched", "evidence_hash": "b" * 64}
                    for target in operation.required_targets
                },
                "staging://onboarding/auditor-scope/" + label.lower(),
            )
            membership.with_user(cls.approver).action_activate()
            assert membership.state == "active"
        cls.role_template = cls.env["codestra.role.template"].create(
            {
                "name": "Onboarding Campaign Agent",
                "code": "ONB_AGENT",
                "company_id": cls.company.id,
                "business_unit_id": cls.unit.id,
                "vicidial_user_group": "ONB_AGENT",
                "requires_mfa": True,
            }
        )
        cls.env["ir.config_parameter"].with_user(SUPERUSER_ID).set_param(
            "codestra.integration.environment", "STAGING"
        )
        cls.env["ir.config_parameter"].with_user(SUPERUSER_ID).set_param(
            "codestra.integration.organization_public_id", "codestra-test"
        )
        cls.env["ir.config_parameter"].with_user(SUPERUSER_ID).set_param(
            "codestra.agent.activation.login_url",
            "https://auth.codestra.co/contact-center/agent",
        )
        cls.env["ir.config_parameter"].with_user(SUPERUSER_ID).set_param(
            "codestra.agent.activation.ttl_minutes", "30"
        )

    @classmethod
    def _create_user(cls, name, login, group_xmlids):
        groups = cls.env["res.groups"].browse(
            [cls.env.ref(xmlid).id for xmlid in group_xmlids]
        )
        return cls.env["res.users"].with_context(no_reset_password=True).create(
            {
                "name": name,
                "login": login,
                "email": login,
                "company_id": cls.company.id,
                "company_ids": [(6, 0, cls.company.ids)],
                "call_center_business_unit_ids": [(6, 0, cls.unit.ids)],
                "call_center_default_business_unit_id": cls.unit.id,
                "group_ids": [(6, 0, groups.ids)],
            }
        )

    def _new_onboarding(self, email="new.agent@example.invalid"):
        employee = self.env["hr.employee"].create(
            {
                "name": "New Campaign Agent",
                "company_id": self.company.id,
                "work_email": email,
                "call_center_branch_id": self.branch.id,
            }
        )
        return self.env["codestra.agent.onboarding"].create(
            {
                "employee_id": employee.id,
                "manager_id": self.requester.id,
                "target_start_date": fields.Date.today(),
                "campaign_id": self.campaign.id,
                "campaign_role": "agent",
                "branch_id": self.branch.id,
                "department_id": self.department.id,
                "operational_team_id": self.team.id,
                "supervisor_id": self.supervisor.id,
                "role_template_id": self.role_template.id,
                "activation_email": email,
                "preferred_language": "en_US",
                "timezone": "UTC",
                "identity_verified": True,
                "employment_documents_complete": True,
                "approved_checks_complete": True,
                "equipment_ready": True,
                "training_complete": True,
                "compliance_approved": True,
            }
        )

    def _prepare(self, onboarding):
        onboarding.with_user(self.requester).action_submit()
        onboarding.with_user(self.approver).action_approve()
        onboarding.with_user(self.requester).action_prepare_access()
        onboarding.invalidate_recordset(
            ["campaign_membership_id", "provisioning_request_id"]
        )
        request_record = onboarding.provisioning_request_id
        request_record.with_user(self.approver).write(
            {
                "operational_approved": True,
                "it_approved": True,
            }
        )
        return request_record

    def _start(self, onboarding):
        request_record = self._prepare(onboarding)
        onboarding.with_user(self.approver).action_start_provisioning()
        onboarding.invalidate_recordset(
            ["state", "provisioning_outbox_id", "campaign_membership_id"]
        )
        request_record.invalidate_recordset(["state", "step_ids"])
        return request_record

    def _match_membership(self, onboarding):
        operation = onboarding.campaign_membership_id._latest_access_grant_operation()
        results = {
            target: {"status": "matched", "evidence_hash": "a" * 64}
            for target in operation.required_targets
        }
        operation.with_user(self.identity_service).action_record_readback(
            results, "staging://agent-onboarding/readback/matched"
        )
        return operation

    def test_approval_requires_all_readiness_gates(self):
        onboarding = self._new_onboarding()
        onboarding.identity_verified = False
        onboarding.with_user(self.requester).action_submit()
        with self.assertRaises(ValidationError):
            onboarding.with_user(self.approver).action_approve()
        onboarding.identity_verified = True
        self.assertEqual(onboarding.completion_percent, 100.0)
        onboarding.with_user(self.approver).action_approve()
        self.assertEqual(onboarding.state, "approved")

    def test_preparation_creates_disabled_user_members_and_request(self):
        onboarding = self._new_onboarding()
        request_record = self._prepare(onboarding)
        user = onboarding.employee_id.with_context(active_test=False).user_id

        self.assertTrue(user)
        self.assertFalse(user.active)
        self.assertEqual(user.login, onboarding.activation_email)
        self.assertEqual(onboarding.campaign_membership_id.state, "pending_approval")
        self.assertEqual(onboarding.campaign_membership_id.user_id, user)
        self.assertEqual(
            onboarding.campaign_membership_id.campaign_id, self.campaign
        )
        self.assertEqual(request_record.state, "pending_approval")
        self.assertEqual(
            request_record.cc_membership_id, onboarding.campaign_membership_id
        )
        self.assertIn(self.legacy_campaign, request_record.campaign_ids)

        existing_membership = onboarding.campaign_membership_id
        existing_request = onboarding.provisioning_request_id
        onboarding.with_user(self.requester).action_prepare_access()
        self.assertEqual(onboarding.campaign_membership_id, existing_membership)
        self.assertEqual(onboarding.provisioning_request_id, existing_request)

    def test_inactive_user_creation_is_safe_under_archived_lookup_context(self):
        onboarding = self._new_onboarding().with_context(active_test=False)
        request_record = self._prepare(onboarding)
        user = onboarding.employee_id.with_context(active_test=False).user_id
        self.assertTrue(user)
        self.assertFalse(user.active)
        self.assertFalse(user.partner_id.active)
        self.assertEqual(request_record.state, "pending_approval")
        self.assertFalse(onboarding.provisioning_outbox_id)
        self.assertFalse(onboarding.activation_outbox_id)

    def test_requester_cannot_approve_the_same_access(self):
        onboarding = self._new_onboarding()
        self._prepare(onboarding)
        with self.assertRaises(AccessError):
            onboarding.with_user(self.requester).action_start_provisioning()

    def test_provisioning_emits_one_secret_free_disabled_event(self):
        onboarding = self._new_onboarding()
        request_record = self._start(onboarding)
        event = onboarding.provisioning_outbox_id
        payload = event.payload_json

        self.assertEqual(onboarding.state, "provisioning")
        self.assertEqual(request_record.state, "provisioning")
        self.assertEqual(onboarding.campaign_membership_id.state, "pending_sync")
        self.assertEqual(event.event_type, "agent.provisioning.requested.v1")
        self.assertEqual(event.delivery_state, "pending")
        self.assertTrue(payload["controls"]["create_disabled"])
        self.assertFalse(payload["controls"]["activate_immediately"])
        self.assertFalse(payload["controls"]["send_activation_email"])
        self.assertFalse(payload["controls"]["plaintext_password_allowed"])
        self.assertFalse(payload["controls"]["production_dialing"])
        self.assertEqual(payload["employee_display_name"], "New Campaign Agent")
        self.assertEqual(payload["vicidial_campaign_id"], "ONB0001")
        self.assertEqual(payload["vicidial_user_group"], "ONB_AGENT")
        self.assertTrue(onboarding.campaign_membership_id.vicidial_user)
        self.assertEqual(
            onboarding.campaign_membership_id.vicidial_user_group, "ONB_AGENT"
        )

        forbidden = {
            "password",
            "temporary_password",
            "token",
            "secret",
            "private_key",
            "activation_link",
            "action_link",
            "reset_link",
        }
        self.assertFalse(forbidden.intersection(_nested_keys(payload)))

        first_event = event
        onboarding.with_user(self.approver).action_start_provisioning()
        self.assertEqual(onboarding.provisioning_outbox_id, first_event)
        self.assertEqual(
            self.env["codestra.runtime.integration.outbox"].search_count(
                [
                    ("aggregate_type", "=", "codestra.agent.onboarding"),
                    ("aggregate_uuid", "=", onboarding.integration_uuid),
                    ("event_type", "=", "agent.provisioning.requested.v1"),
                ]
            ),
            1,
        )

    def test_activation_email_waits_for_complete_readback(self):
        onboarding = self._new_onboarding()
        request_record = self._start(onboarding)

        with self.assertRaises(ValidationError):
            onboarding.with_user(self.approver).action_request_activation_email()

        self._match_membership(onboarding)
        steps = request_record.step_ids
        self.assertTrue(steps, "Provisioning must create steps before verification.")
        # The requester must not be able to forge service verification evidence.
        with self.assertRaises(AccessError):
            steps.with_user(self.requester).write(
                {"state": "verified", "verification_state": "verified"}
            )
        # Service role grants verification writes; the existing user role supplies
        # request access and company/business-unit rules, without approval power.
        provisioning_model = self.env["codestra.provisioning.request"].with_user(
            self.identity_service
        )
        self.assertFalse(provisioning_model.env.su)
        self.assertFalse(self.identity_service.has_group(
            "codestra_identity_provisioning.group_provisioning_approver"
        ))
        callback = {
            "event_id": "onboarding-verified-" + onboarding.integration_uuid,
            "request_id": str(request_record.id),
            "correlation_id": request_record.correlation_id,
            "state": "completed",
            "timestamp": fields.Datetime.to_string(fields.Datetime.now()),
            "step_results": [
                {
                    "target_system": step.target_system,
                    "state": "verified",
                    "evidence_hash": "a" * 64,
                }
                for step in steps
            ],
        }
        self.assertEqual(
            provisioning_model.apply_service_callback(callback), {"state": "accepted"}
        )
        steps.invalidate_recordset(["state", "verification_state"])
        request_record.invalidate_recordset(["state", "mandatory_steps_complete"])
        self.assertEqual(request_record.state, "awaiting_user_activation")
        self.assertTrue(request_record.mandatory_steps_complete)
        self.assertEqual(
            provisioning_model.apply_service_callback(callback), {"state": "replayed"}
        )

        onboarding.with_user(self.approver).action_request_activation_email()
        onboarding.invalidate_recordset(["activation_outbox_id"])
        event = onboarding.activation_outbox_id
        payload = event.payload_json

        self.assertEqual(
            event.event_type, "agent.activation-email.requested.v1"
        )
        self.assertEqual(
            payload["delivery"]["mode"], "keycloak_execute_actions_email"
        )
        self.assertEqual(payload["delivery"]["provider"], "klyrow")
        self.assertEqual(
            payload["login"]["required_actions"],
            ["UPDATE_PASSWORD", "CONFIGURE_TOTP"],
        )
        self.assertEqual(
            payload["login"]["url"],
            "https://auth.codestra.co/contact-center/agent",
        )
        self.assertTrue(payload["controls"]["one_time_action_required"])
        self.assertFalse(payload["controls"]["plaintext_password_allowed"])
        self.assertFalse(payload["controls"]["link_persistence_allowed"])

        forbidden = {
            "password",
            "temporary_password",
            "token",
            "secret",
            "private_key",
            "recovery_code",
            "activation_link",
            "action_link",
            "reset_link",
        }
        self.assertFalse(forbidden.intersection(_nested_keys(payload)))

        first_event = event
        onboarding.with_user(self.approver).action_request_activation_email()
        self.assertEqual(onboarding.activation_outbox_id, first_event)

    def test_campaign_assignment_is_immutable_after_access_preparation(self):
        onboarding = self._new_onboarding()
        self._prepare(onboarding)
        other_legacy = self.legacy_campaign.copy(
            {
                "name": "Other Onboarding Campaign",
                "code": "ONB-OTHER-OUT",
                "team_ids": [(6, 0, self.team.ids)],
                "vicidial_campaign_id": "ONB0002",
            }
        )
        # Copying a legacy campaign also adopts its canonical wrapper.
        other_campaign = self.env["cc.campaign"].with_context(
            active_test=False
        ).search([("legacy_campaign_id", "=", other_legacy.id)])
        other_campaign.ensure_one()
        self.assertEqual(other_campaign.cc_business_unit_id, self.canonical_unit)
        with self.assertRaises(AccessError):
            onboarding.write({"campaign_id": other_campaign.id})


    def test_prepared_request_inputs_cannot_be_changed_even_with_rpc_context(self):
        onboarding = self._new_onboarding()
        self._prepare(onboarding)
        actor = onboarding.with_user(self.requester).with_context(
            codestra_onboarding_scope_migration=True
        )
        self.assertFalse(actor.env.su)
        for name in sorted(IMMUTABLE_ASSIGNMENT_FIELDS):
            value = onboarding[name]
            if onboarding._fields[name].type == "many2one":
                value = value.id
            with self.subTest(field=name), self.assertRaises(AccessError):
                actor.write({name: value})

    def test_secure_onboarding_rejects_disabled_keycloak_before_preparation(self):
        onboarding = self._new_onboarding()
        onboarding.needs_keycloak = False
        with self.assertRaisesRegex(ValidationError, "requires Keycloak"):
            onboarding.with_user(self.requester).action_submit()
        self.assertFalse(onboarding.provisioning_request_id)
        self.assertFalse(onboarding.provisioning_outbox_id)

    def test_campaign_from_another_company_is_rejected(self):
        onboarding = self._new_onboarding()
        company = self.env["res.company"].create({"name": "Other Onboarding Tenant"})
        unit = self.env["call.center.business.unit"].create({
            "name": "Other Onboarding Unit", "code": "ONB-OTHER",
            "company_id": company.id,
        })
        legacy = self.env["call.center.campaign"].create({
            "name": "Other Company Campaign", "code": "ONB-OTHER-CO",
            "business_unit_id": unit.id, "direction": "outbound",
            "design_automation_enabled": False,
        })
        campaign = self.env["cc.campaign"].with_context(active_test=False).search([
            ("legacy_campaign_id", "=", legacy.id),
        ])
        campaign.ensure_one()
        with self.assertRaisesRegex(ValidationError, "belongs to another company"):
            onboarding.write({"campaign_id": campaign.id})

    def test_optional_targets_have_matching_mandatory_steps_and_callbacks(self):
        onboarding = self._new_onboarding()
        onboarding.write({"needs_recording_access": True, "needs_monitoring_access": True})
        provision = self._start(onboarding)
        targets = set(onboarding.provisioning_outbox_id.payload_json["targets"])
        optional = {"voicemail", "recording_access", "monitoring_access"}
        self.assertTrue(optional <= targets)
        self.assertTrue(optional <= set(provision.step_ids.mapped("target_system")))
        for step in provision.step_ids.filtered(lambda row: row.target_system in optional):
            self.assertTrue(step.mandatory)
        # Use the target identifiers that Middleware actually receives, including
        # email_provider's existing explicit alias. Nothing is silently skipped.
        results = [
            {"target_system": target, "state": "verified", "evidence_hash": "d" * 64}
            for target in sorted(targets | {"reconciliation"})
        ]
        callback = {
            "event_id": str(uuid.uuid4()), "request_id": str(provision.id),
            "correlation_id": provision.correlation_id, "state": "completed",
            "timestamp": fields.Datetime.to_string(fields.Datetime.now()),
            "step_results": results,
        }
        service = provision.with_user(self.identity_service)
        self.assertFalse(service.env.su)
        self.assertEqual(service.apply_service_callback(callback), {"state": "accepted"})
        provision.invalidate_recordset(["mandatory_steps_complete", "state"])
        self.assertTrue(provision.mandatory_steps_complete)
        self.assertEqual(provision.state, "awaiting_user_activation")
        self.assertFalse(onboarding.activation_outbox_id)

    def test_activation_evidence_rejects_inferred_failed_and_drifted_results(self):
        onboarding = self._new_onboarding()
        event = self.env["codestra.runtime.integration.outbox"].create_event(
            event_type="agent.activation-email.requested.v1", aggregate=onboarding,
            payload={"controls": {"activate_immediately": False}},
            correlation_id=str(uuid.uuid4()), idempotency_key=uuid.uuid4().hex,
            schema_version="1.0", aggregate_version=1, environment="staging",
            campaign=self.legacy_campaign,
        )
        onboarding._write_system_links({"activation_outbox_id": event.id})
        # A missing explicit-outcome marker covers pre-upgrade, defaulted receipts.
        for explicit, execution, reconciliation in (
            (False, "SUCCEEDED", "RECONCILED"),
            (True, "FAILED", "RECONCILED"),
            (True, "SUCCEEDED", "DRIFTED"),
            (True, "DEAD_LETTERED", "REVIEW_REQUIRED"),
            (True, "SUCCEEDED", "RECONCILED"),
        ):
            values = {
                "name": str(uuid.uuid4()), "result_public_id": str(uuid.uuid4()),
                "schema_version": "1.0", "delivery_id": str(uuid.uuid4()),
                "event_id": event.event_uuid, "registration_id": str(uuid.uuid4()),
                "acknowledgement_id": str(uuid.uuid4()), "correlation_id": event.correlation_id,
                "workflow_id": "onboarding-test", "workflow_version": "1.0",
                "execution_id": str(uuid.uuid4()), "execution_status": execution,
                "result_classification": "COMPLETED", "result_hash": "a" * 64,
                "organization_public_id": "codestra-test", "business_unit_id": self.unit.id,
                "campaign_id": self.legacy_campaign.id, "source_system": "codestra-middleware",
                "source_environment": "staging", "policy_hash": "b" * 64,
                "originating_outbox_id": event.id, "originating_model": onboarding._name,
                "originating_res_id": onboarding.id, "received_at": fields.Datetime.now(),
                "acknowledged_at": fields.Datetime.now(), "processing_status": "RECEIVED",
                "reconciliation_status": reconciliation, "payload_json_redacted": {},
                "request_hash": uuid.uuid4().hex * 2, "created_by_service": "synthetic",
            }
            if explicit:
                values["outcome_explicit"] = True
            result = self.env["codestra.integration.result.inbox"]._create_from_callback(values)
            self.assertFalse(onboarding._successful_activation_results())
            result._mark_processed()
            self.assertEqual(
                bool(onboarding._successful_activation_results()),
                explicit and execution == "SUCCEEDED" and reconciliation == "RECONCILED",
            )
