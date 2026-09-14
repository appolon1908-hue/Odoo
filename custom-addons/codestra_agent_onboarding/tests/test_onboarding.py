import uuid
from unittest.mock import patch

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
        cls.non_admin_manager = cls._create_user(
            "Onboarding Manager (Non-Admin)",
            "onboarding.manager.nonadmin@example.invalid",
            [
                "base.group_user",
                "call_center_core.group_call_center_manager",
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
                # Archiving is an Odoo UI lifecycle concern, not a telephony
                # safety gate. Keep this synthetic campaign readable while its
                # governed reconciliation state remains disabled.
                "active": True,
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
        cls.extension_pool = cls.env["codestra.extension.pool"].create(
            {
                "name": "Onboarding Test Pool",
                "code": "ONB-EXT",
                "business_unit_id": cls.unit.id,
                "start_extension": 7200,
                "end_extension": 7299,
                "context": "codestra_restricted",
                "active": True,
            }
        )
        cls.env["ir.config_parameter"].with_user(SUPERUSER_ID).set_param(
            "codestra.integration.environment", "STAGING"
        )
        cls.env["ir.config_parameter"].with_user(SUPERUSER_ID).set_param(
            "codestra.integration.organization_public_id", "codestra-test"
        )
        cls.env["ir.config_parameter"].with_user(SUPERUSER_ID).set_param(
            "codestra.middleware.tenant_id", "codestra-test"
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

    def _middleware_binding(self, onboarding):
        return {
            "onboarding_uuid": onboarding.integration_uuid,
            "provisioning_request_id": str(onboarding.provisioning_request_id.id),
            "membership_uuid": onboarding.campaign_membership_id.identity_uuid,
            "desired_state_version": onboarding.desired_state_version,
        }

    def _middleware_readback(self, onboarding, **updates):
        return {
            "middleware_request_id": onboarding.middleware_request_id,
            "request_id": onboarding.integration_uuid,
            "tenant_id": "codestra-test",
            "employee_id": onboarding.employee_id.codestra_employee_number,
            "state": "PARTIAL",
            "correlation_id": onboarding.provisioning_request_id.correlation_id,
            "version": onboarding.middleware_version + 1,
            "keycloak_subject": onboarding.keycloak_subject,
            "odoo": self._middleware_binding(onboarding),
            "steps": [],
            **updates,
        }

    def _start(self, onboarding, *, include_keycloak_subject=True):
        request_record = self._prepare(onboarding)
        response = {
            "middleware_request_id": str(uuid.uuid4()),
            "request_id": onboarding.integration_uuid,
            "tenant_id": "codestra-test",
            # The governed start action reserves the employee number immediately
            # before it calls Middleware, so the mock binds its response to the
            # final outbound payload below rather than this pre-reservation value.
            "employee_id": False,
            "state": "PARTIAL",
            "correlation_id": request_record.correlation_id,
            "version": 1,
            "keycloak_subject": str(uuid.uuid4()) if include_keycloak_subject else False,
            "last_error_code": "KILL_SWITCH_CLOSED",
            "last_error_summary": "channel writes are disabled in the test runtime",
            "odoo": {
                "onboarding_uuid": onboarding.integration_uuid,
                "provisioning_request_id": str(request_record.id),
                "membership_uuid": onboarding.campaign_membership_id.identity_uuid,
                "desired_state_version": onboarding.desired_state_version,
            },
            "channels": [],
            "steps": [],
        }
        client = self.env["codestra.agent.provisioning.middleware.client"]

        def middleware_response(_onboarding, payload, **_kwargs):
            return {**response, "employee_id": payload["employee_id"]}

        with patch.object(
            type(client), "_create_request", side_effect=middleware_response
        ):
            onboarding.with_user(self.approver).action_start_provisioning()
        onboarding.invalidate_recordset(
            [
                "state",
                "provisioning_outbox_id",
                "campaign_membership_id",
                "middleware_request_id",
                "middleware_state",
            ]
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

    def _channel(self, onboarding, channel_type):
        return self.env["codestra.agent.channel"].search(
            [
                ("employee_id", "=", onboarding.employee_id.id),
                ("channel_type", "=", channel_type),
            ],
            limit=1,
        )

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
        self.assertEqual(request_record.requested_by, self.requester)
        self.assertEqual(request_record.extension_pool_id, self.extension_pool)
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

    def test_provisioning_calls_canonical_middleware_saga(self):
        onboarding = self._new_onboarding()
        request_record = self._start(onboarding)

        self.assertEqual(onboarding.state, "provisioning")
        self.assertEqual(request_record.state, "partially_provisioned")
        self.assertEqual(onboarding.campaign_membership_id.state, "pending_sync")
        self.assertEqual(onboarding.middleware_state, "PARTIAL")
        self.assertTrue(onboarding.middleware_request_id)
        self.assertTrue(onboarding.keycloak_subject)
        self.assertFalse(onboarding.provisioning_outbox_id)
        self.assertTrue(onboarding.campaign_membership_id.vicidial_user)
        self.assertEqual(
            onboarding.campaign_membership_id.vicidial_user_group, "ONB_AGENT"
        )

        response = {
            "middleware_request_id": onboarding.middleware_request_id,
            "request_id": onboarding.integration_uuid,
            "tenant_id": "codestra-test",
            "employee_id": request_record.employee_id.codestra_employee_number,
            "state": "PARTIAL",
            "correlation_id": request_record.correlation_id,
            "version": 2,
            "keycloak_subject": onboarding.keycloak_subject,
            "last_error_code": "KILL_SWITCH_CLOSED",
            "last_error_summary": "still gated",
            "odoo": {
                "onboarding_uuid": onboarding.integration_uuid,
                "provisioning_request_id": str(request_record.id),
                "membership_uuid": onboarding.campaign_membership_id.identity_uuid,
                "desired_state_version": onboarding.desired_state_version,
            },
            "channels": [],
            "steps": [],
        }
        client = self.env["codestra.agent.provisioning.middleware.client"]
        with patch.object(type(client), "_reconcile_request", return_value=response) as reconcile:
            onboarding.with_user(self.approver).action_start_provisioning()
        reconcile.assert_called_once()
        self.assertEqual(onboarding.middleware_version, 2)
        self.assertEqual(
            self.env["codestra.runtime.integration.outbox"].search_count(
                [
                    ("aggregate_type", "=", "codestra.agent.onboarding"),
                    ("aggregate_uuid", "=", onboarding.integration_uuid),
                    ("event_type", "=", "agent.provisioning.requested.v1"),
                ]
            ),
            0,
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
                "vicidial_user_group": "ONB_AGENT",
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
        targets = set(onboarding._provisioning_event_payload()["targets"])
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
                "reconciliation_status": reconciliation,
                "payload_json_redacted": {"summary": "synthetic"},
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

    def test_extension_is_reserved_and_synced_to_membership(self):
        onboarding = self._new_onboarding()
        self._start(onboarding)
        membership = onboarding.campaign_membership_id
        extension = membership.extension
        self.assertTrue(extension)
        self.assertTrue(
            self.extension_pool.start_extension
            <= int(extension)
            <= self.extension_pool.end_extension
        )
        assignment = self.env["codestra.extension.assignment"].search(
            [("request_id", "=", onboarding.provisioning_request_id.id)]
        )
        self.assertEqual(len(assignment), 1)
        self.assertEqual(assignment.extension, extension)
        self.assertEqual(membership.phone_assignment_id, assignment)
        for channel_type in ("phone", "webrtc"):
            channel = self._channel(onboarding, channel_type)
            self.assertEqual(channel.extension_assignment_id, assignment)
            self.assertEqual(channel.provisioning_request_id, onboarding.provisioning_request_id)
            self.assertEqual(
                channel.correlation_id,
                onboarding.provisioning_request_id.correlation_id,
            )

    def test_webrtc_and_sms_flags_flow_to_membership_and_event_payload(self):
        onboarding = self._new_onboarding(email="webrtc.agent@example.invalid")
        onboarding.write(
            {
                "webrtc_enabled": True,
                "sms_enabled": True,
                "sms_sender": "CODESTRA",
            }
        )
        self._start(onboarding)
        membership = onboarding.campaign_membership_id
        self.assertTrue(self._channel(onboarding, "webrtc").desired_enabled)
        self.assertTrue(self._channel(onboarding, "sms").desired_enabled)
        payload = onboarding._provisioning_event_payload()
        self.assertIn("webrtc", payload["targets"])
        self.assertIn("sms", payload["targets"])
        self.assertEqual(payload["telephony_assignment"]["extension"], membership.extension)
        self.assertTrue(payload["telephony_assignment"]["webrtc_enabled"])
        self.assertTrue(payload["telephony_assignment"]["sms_enabled"])
        self.assertEqual(payload["telephony_assignment"]["webrtc_max_devices"], 1)
        self.assertFalse(payload["controls"]["webrtc_credential_issuance"])

    def test_incoming_and_outgoing_call_permissions_flow_to_phone_and_webrtc_channels(
        self,
    ):
        onboarding = self._new_onboarding(email="calling.agent@example.invalid")
        onboarding.write(
            {
                "webrtc_enabled": True,
                "incoming_calls_enabled": True,
                "outgoing_calls_enabled": True,
            }
        )
        self._start(onboarding)
        phone = self._channel(onboarding, "phone")
        webrtc = self._channel(onboarding, "webrtc")
        self.assertTrue(phone.incoming_allowed)
        self.assertTrue(phone.outgoing_allowed)
        self.assertTrue(webrtc.incoming_allowed)
        self.assertTrue(webrtc.outgoing_allowed)
        email = self._channel(onboarding, "email")
        self.assertFalse(email.incoming_allowed)
        self.assertFalse(email.outgoing_allowed)

    def test_calling_permissions_require_sip_endpoint(self):
        onboarding = self._new_onboarding(email="calling.no.sip@example.invalid")
        with self.assertRaises(ValidationError):
            onboarding.write(
                {"needs_sip_endpoint": False, "outgoing_calls_enabled": True}
            )

    def test_webrtc_and_sip_require_the_current_vicidial_transport(self):
        onboarding = self._new_onboarding(email="webrtc.no.sip@example.invalid")
        with self.assertRaises(ValidationError):
            onboarding.write({"needs_sip_endpoint": False, "webrtc_enabled": True})

        onboarding = self._new_onboarding(email="sip.no.vicidial@example.invalid")
        with self.assertRaises(ValidationError):
            onboarding.write({"needs_vicidial": False})

    def test_middleware_payload_preserves_approved_call_permissions(self):
        onboarding = self._new_onboarding(email="calling.payload@example.invalid")
        onboarding.write({
            "incoming_calls_enabled": True,
            "outgoing_calls_enabled": False,
        })
        self._start(onboarding)
        payload = onboarding._middleware_provisioning_payload()
        self.assertTrue(payload["telephony"]["incoming_allowed"])
        self.assertFalse(payload["telephony"]["outgoing_allowed"])
        self.assertEqual(
            payload["telephony"]["existing_extension"],
            onboarding.campaign_membership_id.extension,
        )
        self.assertRegex(
            payload["campaigns"][0]["vicidial_user_id"],
            r"^[A-Z]{3}[0-9]{4,12}$",
        )

    def test_middleware_payload_preserves_optional_entitlements(self):
        onboarding = self._new_onboarding(email="entitlements.payload@example.invalid")
        onboarding.write({
            "needs_agent_desktop": False,
            "needs_voicemail": True,
            "needs_recording_access": True,
            "needs_monitoring_access": True,
        })
        self._start(onboarding)
        payload = onboarding._middleware_provisioning_payload()
        self.assertEqual(
            payload["entitlements"],
            {
                "agent_desktop": False,
                "voicemail": True,
                "recording_access": True,
                "monitoring_access": True,
            },
        )

    def test_middleware_accepts_an_accepted_nonterminal_response(self):
        onboarding = self._new_onboarding(email="async.middleware@example.invalid")
        request_record = self._prepare(onboarding)
        request_record.with_user(self.approver).action_approve()
        request_record.with_user(SUPERUSER_ID).action_reserve_identifiers()
        request_record.employee_id.invalidate_recordset(["codestra_employee_number"])
        middleware_request_id = str(uuid.uuid4())
        response = {
            "middleware_request_id": middleware_request_id,
            "request_id": onboarding.integration_uuid,
            "tenant_id": "codestra-test",
            "employee_id": request_record.employee_id.codestra_employee_number,
            "state": "READBACK",
            "correlation_id": request_record.correlation_id,
            "version": 1,
            "odoo": self._middleware_binding(onboarding),
            "keycloak_subject": False,
            "last_error_code": False,
            "last_error_summary": False,
            "channels": [],
            "steps": [],
        }
        result = onboarding._apply_middleware_result(response)
        self.assertEqual(result["state"], "accepted")
        self.assertEqual(onboarding.middleware_request_id, middleware_request_id)
        self.assertEqual(onboarding.middleware_state, "READBACK")
        self.assertEqual(request_record.state, "provisioning")

    def test_middleware_step_history_keeps_only_the_latest_channel_result(self):
        rows = self.env[
            "codestra.agent.onboarding"
        ]._middleware_channel_status_from_steps(
            [
                {
                    "system": "klyrow",
                    "operation": "provision_sender_identity",
                    "state": "skipped",
                    "external_reference": False,
                    "error_code": "KILL_SWITCH_CLOSED",
                    "error_summary": "disabled",
                    "readback_state": False,
                    "completed_at": "2026-09-13T10:00:00Z",
                },
                {
                    "system": "klyrow",
                    "operation": "provision_sender_identity",
                    "state": "succeeded",
                    "external_reference": "sender-new",
                    "error_code": False,
                    "error_summary": False,
                    "readback_state": "sender_identity_active",
                    "completed_at": "2026-09-13T10:01:00Z",
                },
            ]
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["channel"], "email")
        self.assertEqual(rows[0]["provider_reference"], "sender-new")
        self.assertTrue(rows[0]["effective_access"])

    def test_skipped_and_requested_steps_never_satisfy_verification(self):
        onboarding = self.env["codestra.agent.onboarding"]
        self.assertEqual(
            onboarding._middleware_step_state("skipped", "kill_switch_closed"),
            ("blocked", "failed"),
        )
        self.assertEqual(
            onboarding._middleware_step_state(
                "succeeded", "sender_profile_requested"
            ),
            ("verification_pending", "pending"),
        )

    def test_middleware_commits_only_the_exact_reserved_extension(self):
        onboarding = self._new_onboarding(email="extension.readback@example.invalid")
        request_record = self._start(onboarding)
        assignment = onboarding.campaign_membership_id.phone_assignment_id
        response = {
            "middleware_request_id": onboarding.middleware_request_id,
            "request_id": onboarding.integration_uuid,
            "tenant_id": "codestra-test",
            "employee_id": request_record.employee_id.codestra_employee_number,
            "state": "PARTIAL",
            "correlation_id": request_record.correlation_id,
            "version": 2,
            "odoo": self._middleware_binding(onboarding),
            "keycloak_subject": onboarding.keycloak_subject,
            "steps": [
                {
                    "system": "vicidial",
                    "operation": "adopt_extension",
                    "state": "succeeded",
                    "external_reference": assignment.extension,
                    "readback_state": "phone_active",
                }
            ],
        }
        onboarding._apply_middleware_result(response)
        assignment.invalidate_recordset(["state", "committed_at"])
        self.assertEqual(assignment.state, "committed")
        self.assertTrue(assignment.committed_at)
        self.assertEqual(self._channel(onboarding, "phone").state, "provisioned")

    def test_middleware_extension_mismatch_fails_closed(self):
        onboarding = self._new_onboarding(email="extension.mismatch@example.invalid")
        request_record = self._start(onboarding)
        assignment = onboarding.campaign_membership_id.phone_assignment_id
        response = {
            "middleware_request_id": onboarding.middleware_request_id,
            "request_id": onboarding.integration_uuid,
            "tenant_id": "codestra-test",
            "employee_id": request_record.employee_id.codestra_employee_number,
            "state": "PARTIAL",
            "correlation_id": request_record.correlation_id,
            "version": 2,
            "odoo": self._middleware_binding(onboarding),
            "keycloak_subject": onboarding.keycloak_subject,
            "steps": [
                {
                    "system": "vicidial",
                    "operation": "adopt_extension",
                    "state": "succeeded",
                    "external_reference": "9999",
                    "readback_state": "phone_active",
                }
            ],
        }
        onboarding._apply_middleware_result(response)
        assignment.invalidate_recordset(["state"])
        request_record.invalidate_recordset(["mandatory_steps_complete"])
        phone = self._channel(onboarding, "phone")
        phone.invalidate_recordset(["state", "last_error_code"])
        self.assertEqual(assignment.state, "reserved")
        self.assertEqual(phone.state, "failed")
        self.assertEqual(phone.last_error_code, "EXTENSION_READBACK_MISMATCH")
        self.assertFalse(request_record.mandatory_steps_complete)

    def test_middleware_saga_and_keycloak_identities_are_immutable(self):
        onboarding = self._new_onboarding(email="immutable.saga@example.invalid")
        request_record = self._start(onboarding)
        base = {
            "middleware_request_id": onboarding.middleware_request_id,
            "request_id": onboarding.integration_uuid,
            "tenant_id": "codestra-test",
            "employee_id": request_record.employee_id.codestra_employee_number,
            "state": "PARTIAL",
            "correlation_id": request_record.correlation_id,
            "version": 2,
            "odoo": self._middleware_binding(onboarding),
            "keycloak_subject": onboarding.keycloak_subject,
            "steps": [],
        }
        with self.assertRaisesRegex(ValueError, "middleware_request_identity_mismatch"):
            onboarding._apply_middleware_result(
                {**base, "middleware_request_id": str(uuid.uuid4())}
            )
        with self.assertRaisesRegex(ValueError, "middleware_keycloak_subject_mismatch"):
            onboarding._apply_middleware_result(
                {**base, "keycloak_subject": str(uuid.uuid4())}
            )
        with self.assertRaisesRegex(ValueError, "middleware_employee_binding_mismatch"):
            onboarding._apply_middleware_result(
                {**base, "employee_id": "OTHER-EMPLOYEE"}
            )

    def test_middleware_rejects_missing_or_incomplete_odoo_binding(self):
        onboarding = self._new_onboarding(email="required.binding@example.invalid")
        request_record = self._start(onboarding)
        response = self._middleware_readback(onboarding, state="EFFECTIVE")
        missing = dict(response)
        missing.pop("odoo")
        cases = [missing, {**response, "odoo": {}}, {**response, "odoo": None}]
        for field in self._middleware_binding(onboarding):
            binding = self._middleware_binding(onboarding)
            binding.pop(field)
            cases.append({**response, "odoo": binding})
        before = request_record.step_ids.read(["state", "verification_state"])
        for invalid in cases:
            with self.subTest(binding=invalid.get("odoo")):
                with self.assertRaisesRegex(ValueError, "middleware_odoo_binding"):
                    onboarding._apply_middleware_result(invalid)
                self.assertEqual(onboarding.middleware_version, 1)
                self.assertEqual(request_record.state, "partially_provisioned")
                self.assertNotEqual(onboarding.campaign_membership_id.last_sync_status, "matched")
                self.assertEqual(
                    request_record.step_ids.read(["state", "verification_state"]), before
                )

    def test_middleware_effective_requires_a_keycloak_subject(self):
        onboarding = self._new_onboarding(email="required.subject@example.invalid")
        request_record = self._start(onboarding, include_keycloak_subject=False)
        self.assertTrue(onboarding.needs_keycloak)
        # Even complete step evidence cannot substitute for the immutable identity.
        request_record.step_ids.with_user(SUPERUSER_ID).write(
            {"state": "verified", "verification_state": "verified"}
        )
        self.assertTrue(request_record.mandatory_steps_complete)
        response = self._middleware_readback(onboarding, state="EFFECTIVE")
        for subject in (None, False, "", "   ", 123, "x" * 65):
            with self.subTest(subject=subject):
                with self.assertRaisesRegex(ValueError, "middleware_keycloak_subject"):
                    onboarding._apply_middleware_result({**response, "keycloak_subject": subject})
                self.assertEqual(onboarding.middleware_version, 1)
                self.assertEqual(request_record.state, "partially_provisioned")
                self.assertFalse(onboarding.keycloak_subject)
                self.assertNotEqual(onboarding.campaign_membership_id.last_sync_status, "matched")
        missing = dict(response)
        missing.pop("keycloak_subject")
        with self.assertRaisesRegex(ValueError, "middleware_keycloak_subject_required"):
            onboarding._apply_middleware_result(missing)
        with self.assertRaises(ValidationError):
            onboarding.with_user(self.approver).action_request_activation_email()
        subject = str(uuid.uuid4())
        onboarding._apply_middleware_result({**response, "keycloak_subject": subject})
        self.assertEqual(onboarding.keycloak_subject, subject)
        self.assertEqual(onboarding.campaign_membership_id.keycloak_subject, subject)
        self.assertEqual(request_record.state, "awaiting_user_activation")
        # Later observations may omit a subject already bound to this same saga.
        followup = self._middleware_readback(onboarding, state="EFFECTIVE")
        followup.pop("keycloak_subject")
        onboarding._apply_middleware_result(followup)
        self.assertEqual(onboarding.keycloak_subject, subject)

    def test_middleware_extension_history_uses_latest_adoption(self):
        for old_operation in ("adopt_extension", "reserve_extension"):
            with self.subTest(old_operation=old_operation):
                onboarding = self._new_onboarding(
                    email="latest.%s@example.invalid" % old_operation
                )
                self._start(onboarding)
                assignment = onboarding.campaign_membership_id.phone_assignment_id
                response = self._middleware_readback(onboarding, steps=[
                    {"system": "vicidial", "operation": old_operation,
                     "state": "succeeded", "external_reference": "9999",
                     "readback_state": "phone_active", "attempt": 1},
                    {"system": "vicidial", "operation": "adopt_extension",
                     "state": "succeeded", "external_reference": assignment.extension,
                     "readback_state": "phone_active", "attempt": 2},
                ])
                onboarding._apply_middleware_result(response)
                self.assertEqual(assignment.state, "committed")
                self.assertEqual(assignment.provider_reference, assignment.extension)
                phone = self._channel(onboarding, "phone")
                self.assertEqual(phone.state, "provisioned")
                self.assertFalse(phone.last_error_code)

    def test_middleware_latest_extension_failure_does_not_commit_old_success(self):
        onboarding = self._new_onboarding(email="latest.failure@example.invalid")
        self._start(onboarding)
        assignment = onboarding.campaign_membership_id.phone_assignment_id
        response = self._middleware_readback(onboarding, steps=[
            {"system": "vicidial", "operation": "adopt_extension",
             "state": "succeeded", "external_reference": assignment.extension,
             "readback_state": "phone_active", "attempt": 1},
            {"system": "vicidial", "operation": "adopt_extension",
             "state": "failed", "external_reference": assignment.extension,
             "error_code": "READBACK_FAILED", "attempt": 2},
        ])
        onboarding._apply_middleware_result(response)
        self.assertEqual(assignment.state, "reserved")
        self.assertFalse(assignment.committed_at)
        self.assertEqual(self._channel(onboarding, "phone").state, "failed")

    def test_membership_channel_ids_reflect_created_channels(self):
        onboarding = self._new_onboarding(email="channel.reflection@example.invalid")
        self._start(onboarding)
        membership = onboarding.campaign_membership_id
        self.assertEqual(len(membership.channel_ids), 4)
        self.assertEqual(
            set(membership.channel_ids.mapped("channel_type")),
            {"email", "sms", "phone", "webrtc"},
        )

    def test_communication_channel_switches_require_global_administrator(self):
        onboarding = self._new_onboarding(email="channel.switch.rbac@example.invalid")
        for field_name, value in (
            ("needs_company_email", False),
            ("needs_sip_endpoint", False),
            ("webrtc_enabled", True),
            ("sms_enabled", True),
        ):
            with self.subTest(field=field_name), self.assertRaises(AccessError):
                onboarding.with_user(self.non_admin_manager).write({field_name: value})
        onboarding.with_user(self.requester).write(
            {
                "webrtc_enabled": True,
                "sms_enabled": True,
                "sms_sender": "CODESTRA",
            }
        )
        self.assertTrue(onboarding.webrtc_enabled)
        self.assertTrue(onboarding.sms_enabled)

        with self.assertRaises(AccessError):
            self.env["codestra.agent.onboarding"].with_user(
                self.non_admin_manager
            ).create(
                {
                    "employee_id": self.env["hr.employee"].create(
                        {
                            "name": "Channel Switch RBAC Candidate",
                            "company_id": self.company.id,
                            "call_center_branch_id": self.branch.id,
                        }
                    ).id,
                    "manager_id": self.requester.id,
                    "target_start_date": fields.Date.today(),
                    "campaign_id": self.campaign.id,
                    "campaign_role": "agent",
                    "branch_id": self.branch.id,
                    "department_id": self.department.id,
                    "operational_team_id": self.team.id,
                    "supervisor_id": self.supervisor.id,
                    "role_template_id": self.role_template.id,
                    "activation_email": "channel.switch.rbac.create@example.invalid",
                    "preferred_language": "en_US",
                    "timezone": "UTC",
                    "webrtc_enabled": True,
                }
            )

    def test_communication_channel_switches_are_on_the_onboarding_form(self):
        views = self.env["codestra.agent.onboarding"].get_views(
            [(False, "form")], {"toolbar": False}
        )
        arch = views["views"]["form"]["arch"]
        for field_name in (
            "needs_company_email",
            "sms_enabled",
            "needs_sip_endpoint",
            "webrtc_enabled",
        ):
            self.assertIn(field_name, views["models"]["codestra.agent.onboarding"]["fields"])
            self.assertIn(
                'name="%s" widget="boolean_toggle"' % field_name, arch
            )

    def test_webrtc_and_sms_default_to_disabled(self):
        onboarding = self._new_onboarding(email="no.webrtc.agent@example.invalid")
        self._start(onboarding)
        self.assertFalse(self._channel(onboarding, "webrtc").desired_enabled)
        self.assertFalse(self._channel(onboarding, "sms").desired_enabled)
        payload = onboarding._provisioning_event_payload()
        self.assertNotIn("webrtc", payload["targets"])
        self.assertNotIn("sms", payload["targets"])

    def test_webrtc_session_single_device_enforced_and_revoked_on_disable(self):
        onboarding = self._new_onboarding(email="single.device.agent@example.invalid")
        onboarding.webrtc_enabled = True
        self._start(onboarding)
        membership = onboarding.campaign_membership_id
        Session = self.env["cc.webrtc.session"]
        first = Session.action_register(membership, "First Browser")
        self.assertTrue(first.active_session)
        second = Session.action_register(membership, "Second Browser")
        first.invalidate_recordset(["active_session", "revoked_at"])
        self.assertFalse(first.active_session)
        self.assertTrue(second.active_session)
        self._channel(onboarding, "webrtc").write({"desired_enabled": False})
        second.invalidate_recordset(["active_session", "revoked_at"])
        self.assertFalse(second.active_session)

    def test_platform_user_dashboard_reflects_channel_and_drift_state(self):
        tenant = self.env["codestra.tenant"].with_user(SUPERUSER_ID).create({
            "name": "Dashboard Synthetic Tenant", "code": "DASH-TENANT",
        })
        platform_user = self.env["codestra.platform.user"].with_user(SUPERUSER_ID).create({
            "name": "Dashboard Platform User",
            "primary_email": "dashboard.platform.user@example.invalid",
            "tenant_id": tenant.id,
        })
        onboarding = self._new_onboarding(email="dashboard.agent@example.invalid")
        onboarding.write({
            "needs_company_email": True,
            "needs_sip_endpoint": True,
            "sms_enabled": False,
            "webrtc_enabled": False,
        })
        self._start(onboarding)
        membership = onboarding.campaign_membership_id
        membership.with_user(SUPERUSER_ID).write({"platform_user_id": platform_user.id})
        platform_user.invalidate_recordset()

        # email/phone are desired-but-not-yet-effective ("pending");
        # sms/webrtc were never requested at all ("off").
        self.assertEqual(platform_user.channel_status_email, "pending")
        self.assertEqual(platform_user.channel_status_phone, "pending")
        self.assertEqual(platform_user.channel_status_sms, "off")
        self.assertEqual(platform_user.channel_status_webrtc, "off")
        self.assertEqual(platform_user.provisioning_drift_status, "drift")
        self.assertIn(membership, platform_user.membership_ids)

    def test_webrtc_session_requires_webrtc_enabled(self):
        onboarding = self._new_onboarding(email="webrtc.disabled.agent@example.invalid")
        self._start(onboarding)
        membership = onboarding.campaign_membership_id
        self.assertFalse(self._channel(onboarding, "webrtc").desired_enabled)
        with self.assertRaises(ValidationError):
            self.env["cc.webrtc.session"].action_register(membership, "Browser")

    def test_second_active_webrtc_session_rejected_at_the_database(self):
        """action_register() itself auto-revokes the prior session before
        creating a new one (a deliberate "new login wins" design covered by
        test_webrtc_session_single_device_enforced_and_revoked_on_disable).
        This test instead proves the structural backstop underneath that
        method: _one_active_session_per_membership rejects a second
        unrevoked row for the same membership outright, for any caller
        that does not go through action_register's revoke-then-create path.
        """
        from ..models.telephony_assignment import SESSION_WRITE_CAPABILITY

        onboarding = self._new_onboarding(email="second.active.session@example.invalid")
        onboarding.webrtc_enabled = True
        self._start(onboarding)
        membership = onboarding.campaign_membership_id
        self.env["cc.webrtc.session"].action_register(membership, "First Browser")
        with self.assertRaises(Exception):
            self.env["cc.webrtc.session"].with_context(
                _cc_webrtc_session_write=SESSION_WRITE_CAPABILITY
            ).create({"membership_id": membership.id, "device_label": "Second Browser"})

    def test_email_collision_falls_back_to_firstname_lastname_then_numbered(self):
        def _onboarding_for(name, email):
            employee = self.env["hr.employee"].create(
                {
                    "name": name,
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

        # Every candidate below is a distinct new hire who happens to share the
        # same requested address and first name — never the same person as an
        # earlier candidate, so each must land on its own new account.
        first = _onboarding_for("Maria Lopez", "maria@example.invalid")
        self._prepare(first)
        self.assertEqual(first.employee_id.user_id.login, "maria@example.invalid")

        # Same first AND last name as `first`: "maria@" is taken, and so is
        # "maria.lopez@" would be if it were a repeat - here it's the first
        # attempt at that candidate, so it succeeds.
        second = _onboarding_for("Maria Lopez", "maria@example.invalid")
        self._prepare(second)
        self.assertEqual(
            second.employee_id.user_id.login, "maria.lopez@example.invalid"
        )
        self.assertNotEqual(second.employee_id.user_id, first.employee_id.user_id)

        # A third "Maria Lopez": both "maria@" and "maria.lopez@" are now
        # taken, so this falls through to the numbered suffix.
        third = _onboarding_for("Maria Lopez", "maria@example.invalid")
        self._prepare(third)
        self.assertEqual(third.employee_id.user_id.login, "maria2@example.invalid")

        fourth = _onboarding_for("Maria Lopez", "maria@example.invalid")
        self._prepare(fourth)
        self.assertEqual(fourth.employee_id.user_id.login, "maria3@example.invalid")

    def test_email_collision_never_attaches_to_an_existing_account(self):
        existing_user = self.env["res.users"].with_context(
            no_reset_password=True
        ).create(
            {
                "name": "Existing Account",
                "login": "shared@example.invalid",
                "email": "shared@example.invalid",
                "company_id": self.company.id,
                "company_ids": [(6, 0, self.company.ids)],
            }
        )
        employee = self.env["hr.employee"].create(
            {
                "name": "Shared Name",
                "company_id": self.company.id,
                "work_email": "shared@example.invalid",
                "call_center_branch_id": self.branch.id,
            }
        )
        onboarding = self.env["codestra.agent.onboarding"].create(
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
                "activation_email": "shared@example.invalid",
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
        self._prepare(onboarding)
        self.assertNotEqual(employee.user_id, existing_user)
        self.assertEqual(
            employee.user_id.login, "shared.name@example.invalid"
        )

    def test_duplicate_platform_user_campaign_membership_rejected(self):
        tenant = self.env["codestra.tenant"].with_user(SUPERUSER_ID).create({
            "name": "Onboarding Synthetic Tenant", "code": "ONB-TENANT",
        })
        platform_user = self.env["codestra.platform.user"].with_user(SUPERUSER_ID).create({
            "name": "Duplicate Membership Platform User",
            "primary_email": "duplicate.membership.platform.user@example.invalid",
            "tenant_id": tenant.id,
        })
        first_user = self._create_user(
            "Duplicate Membership User One",
            "duplicate.membership.one@example.invalid",
            ["base.group_user"],
        )
        second_user = self._create_user(
            "Duplicate Membership User Two",
            "duplicate.membership.two@example.invalid",
            ["base.group_user"],
        )
        first_employee = self.env["hr.employee"].create(
            {"name": "First Slot", "user_id": first_user.id}
        )
        second_employee = self.env["hr.employee"].create(
            {"name": "Second Slot", "user_id": second_user.id}
        )
        self.env["cc.campaign.membership"].create({
            "user_id": first_user.id,
            "employee_id": first_employee.id,
            "campaign_id": self.campaign.id,
            "role": "agent",
            "requested_by_id": self.requester.id,
            "source_ticket": "DUP-MEMBERSHIP-1",
            "starts_at": fields.Datetime.now(),
            "platform_user_id": platform_user.id,
        })
        with self.assertRaises(Exception):
            self.env["cc.campaign.membership"].create({
                "user_id": second_user.id,
                "employee_id": second_employee.id,
                "campaign_id": self.campaign.id,
                "role": "agent",
                "requested_by_id": self.requester.id,
                "source_ticket": "DUP-MEMBERSHIP-2",
                "starts_at": fields.Datetime.now(),
                "platform_user_id": platform_user.id,
            })


    def test_provisioning_transport_is_private_to_rpc(self):
        from odoo.orm.utils import check_method_name
        for model_name in ("codestra.agent.provisioning.middleware.client",
                           "codestra.middleware.agent.provisioning.transport"):
            model = self.env[model_name]
            for method in ("create_request", "reconcile_request"):
                self.assertFalse(hasattr(model, method))
                with self.assertRaises(AccessError):
                    check_method_name("_" + method)

    def test_transport_requires_approved_onboarding(self):
        onboarding = self._new_onboarding().with_user(self.approver)
        client = self.env["codestra.agent.provisioning.middleware.client"].with_user(self.approver)
        with self.assertRaises(AccessError):
            client._create_request(onboarding, {"request_id": onboarding.integration_uuid},
                                   idempotency_key=str(uuid.uuid4()), correlation_id="unapproved")

    def test_provisioning_credentials_reject_group_read(self):
        import tempfile
        from pathlib import Path
        from odoo.addons.codestra_middleware_bridge.models.agent_provisioning_transport import (
            _protected_value,
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credential"
            path.write_text("synthetic-runtime-test-value")
            path.chmod(0o640)
            with self.assertRaises(ValidationError):
                _protected_value(str(path), "test")
            path.chmod(0o600)
            self.assertEqual(_protected_value(str(path), "test"), "synthetic-runtime-test-value")

    def test_reconcile_response_must_return_the_requested_middleware_saga(self):
        from odoo.addons.codestra_middleware_bridge.models.agent_provisioning_transport import (
            MiddlewareProvisioningOutcomeUnknown,
        )

        expected = str(uuid.uuid4())
        response = {
            "middleware_request_id": str(uuid.uuid4()),
            "request_id": str(uuid.uuid4()),
            "tenant_id": "codestra-test",
            "employee_id": "COD00001",
            "state": "PARTIAL",
            "correlation_id": str(uuid.uuid4()),
            "version": 1,
            "steps": [],
        }
        transport = self.env["codestra.middleware.agent.provisioning.transport"]
        with self.assertRaises(MiddlewareProvisioningOutcomeUnknown):
            transport._validate_response(
                response,
                request_id=response["request_id"],
                correlation_id=response["correlation_id"],
                middleware_request_id=expected,
            )
