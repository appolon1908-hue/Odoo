from datetime import date
from unittest.mock import patch

from psycopg2.errors import UniqueViolation

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from ..models.provisioning import ProvisioningRequest
from ..models.provisioning_service import PrivateProvisioningService


@tagged("post_install", "-at_install")
class TestIdentityProvisioning(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.unit = cls.env["call.center.business.unit"].create({
            "name": "Synthetic Transportation",
            "code": "SYN-TRN",
        })
        cls.department = cls.env["call.center.department"].create({
            "name": "Synthetic Operations",
            "code": "SYN-OPS",
            "business_unit_id": cls.unit.id,
        })
        cls.supervisor = cls.env["res.users"].create({
            "name": "Synthetic Supervisor",
            "login": "synthetic.supervisor",
            "call_center_business_unit_ids": [(6, 0, cls.unit.ids)],
            "call_center_default_business_unit_id": cls.unit.id,
        })
        cls.team = cls.env["call.center.team"].create({
            "name": "Synthetic Team",
            "code": "SYN-T1",
            "business_unit_id": cls.unit.id,
            "department_id": cls.department.id,
            "supervisor_ids": [(6, 0, cls.supervisor.ids)],
        })
        cls.employee = cls.env["hr.employee"].create({"name": "Synthetic Employee"})
        cls.template = cls.env["codestra.role.template"].create({
            "name": "Synthetic Agent",
            "code": "SYN_AGENT",
            "business_unit_id": cls.unit.id,
            "company_id": cls.env.company.id,
        })
        cls.monitoring_user = cls.env["res.users"].create({
            "name": "Scoped Monitoring User",
            "login": "synthetic.monitoring",
            "group_ids": [(6, 0, (
                cls.env.ref("base.group_user")
                | cls.env.ref("codestra_identity_provisioning.group_provisioning_user")
            ).ids)],
            "call_center_business_unit_ids": [(6, 0, cls.unit.ids)],
            "call_center_default_business_unit_id": cls.unit.id,
        })

    def _request_values(self, key="synthetic-idempotency"):
        return {
            "request_type": "onboard",
            "employee_id": self.employee.id,
            "supervisor_id": self.supervisor.id,
            "company_id": self.env.company.id,
            "business_unit_id": self.unit.id,
            "department_id": self.department.id,
            "operational_team_id": self.team.id,
            "role_template_id": self.template.id,
            "start_date": date.today(),
            "idempotency_key": key,
        }

    def test_timezone_selection_works_during_fields_get(self):
        descriptions = self.env["codestra.provisioning.request"].fields_get(
            ["timezone"]
        )
        selection = descriptions["timezone"]["selection"]
        self.assertIsInstance(selection, list)
        self.assertIn(("UTC", "UTC"), selection)

    def test_timezone_selection_works_during_get_views(self):
        result = self.env["codestra.provisioning.request"].get_views(
            [(False, "form")], {"toolbar": False}
        )
        self.assertIn("form", result["views"])
        self.assertIn(
            "timezone",
            result["models"]["codestra.provisioning.request"]["fields"],
        )

    def test_new_request_default_get_evaluates_timezone(self):
        defaults = self.env["codestra.provisioning.request"].default_get(
            ["timezone", "state", "request_type"]
        )
        self.assertTrue(defaults["timezone"])
        self.assertEqual(defaults["state"], "draft")
        self.assertEqual(defaults["request_type"], "onboard")

    def test_existing_request_form_fields_are_readable(self):
        request = self.env["codestra.provisioning.request"].create(
            self._request_values("timezone-existing-request")
        )
        values = request.read(["request_number", "timezone", "state"])[0]
        self.assertEqual(values["request_number"], request.request_number)
        self.assertEqual(values["timezone"], request.timezone)
        self.assertEqual(values["state"], "draft")

    def test_administrator_can_evaluate_request_form_metadata(self):
        administrator = self.env.ref("base.user_admin")
        model = self.env["codestra.provisioning.request"].with_user(administrator)
        descriptions = model.fields_get(["timezone"])
        views = model.get_views([(False, "form")], {"toolbar": False})
        self.assertTrue(descriptions["timezone"]["selection"])
        self.assertIn("form", views["views"])

    def test_unauthorized_user_cannot_read_existing_request(self):
        request = self.env["codestra.provisioning.request"].create(
            self._request_values("timezone-unauthorized-request")
        )
        user = self.env["res.users"].create({
            "name": "Timezone Unauthorized User",
            "login": "timezone.unauthorized",
        })
        with self.assertRaises(AccessError):
            request.with_user(user).read(["timezone"])

    def test_duplicate_request_returns_existing_request(self):
        first = self.env["codestra.provisioning.request"].create(
            self._request_values()
        )
        repeated = self.env["codestra.provisioning.request"].create(
            self._request_values()
        )
        self.assertEqual(first, repeated)

    def test_identifier_normalization_and_collision(self):
        request = self.env["codestra.provisioning.request"].create(
            self._request_values("reservation-request")
        )
        model = self.env["codestra.identifier.reservation"]
        model.create({
            "identifier_type": "keycloak_username",
            "normalized_value": "María O Lopez",
            "request_id": request.id,
        })
        with self.assertRaises(UniqueViolation):
            model.create({
                "identifier_type": "keycloak_username",
                "normalized_value": "maria-o-lopez",
                "request_id": request.id,
            })

    def test_vicidial_collision_suffix_stays_within_provider_limit(self):
        first_request = self.env["codestra.provisioning.request"].create(
            self._request_values("vicidial-limit-first")
        )
        second_request = self.env["codestra.provisioning.request"].create(
            self._request_values("vicidial-limit-second")
        )
        base = "synthetic-identifier-longer-than-twenty"
        first = first_request._reserve_identifier(
            "vicidial_username", base, max_length=20, suffix_separator=""
        )
        second = second_request._reserve_identifier(
            "vicidial_username", base, max_length=20, suffix_separator=""
        )
        self.assertNotEqual(first.normalized_value, second.normalized_value)
        self.assertLessEqual(len(first.normalized_value), 20)
        self.assertLessEqual(len(second.normalized_value), 20)
        self.assertTrue(second.normalized_value.endswith("2"))

    def test_extension_6101_is_hard_excluded(self):
        request = self.env["codestra.provisioning.request"].create(
            self._request_values("extension-request")
        )
        pool = self.env["codestra.extension.pool"].create({
            "name": "Synthetic 6100 Pool",
            "code": "SYN-61",
            "business_unit_id": self.unit.id,
            "start_extension": 6100,
            "end_extension": 6102,
            "context": "codestra_restricted",
            "active": True,
        })
        first = pool.reserve_extension(self.employee, request)
        second = pool.reserve_extension(self.employee, request)
        self.assertEqual(first.extension, "6100")
        self.assertEqual(second.extension, "6102")

    def test_role_privilege_change_creates_new_version(self):
        self.template.write({"allows_transfer": True})
        versions = self.env["codestra.role.template"].with_context(
            active_test=False
        ).search(
            [("code", "=", self.template.code)], order="version"
        )
        self.assertEqual(versions.mapped("version"), [1, 2])
        self.assertFalse(versions[0].active)
        self.assertTrue(versions[1].allows_transfer)

    def test_credential_model_has_no_secret_value_field(self):
        fields = set(self.env["codestra.credential.reference"]._fields)
        forbidden = {
            "password", "secret", "secret_value", "token", "api_token",
            "private_key", "turn_secret", "sip_password",
        }
        self.assertFalse(fields & forbidden)

    def test_mailbox_projection_has_only_approved_business_fields(self):
        model = self.env["codestra.company.mailbox"]
        approved = {
            "email_address", "provider", "external_mailbox_id", "aliases",
            "provisioning_state", "created_at", "activated_at", "suspended_at",
            "terminated_at", "credential_reference",
        }
        framework = {
            "id", "display_name", "create_uid", "create_date", "write_uid",
            "write_date", "__last_update",
        }
        self.assertEqual(set(model._fields) - framework, approved)
        forbidden = {
            "password", "secret", "secret_value", "token", "api_token",
            "private_key", "recovery_code",
        }
        self.assertFalse(set(model._fields) & forbidden)

    def test_mailbox_alias_validation_and_collision(self):
        credential = self.env["codestra.credential.reference"].create({
            "name": "Synthetic mailbox credential",
            "system": "synthetic_mail_sink",
            "secret_backend": "protected_file",
            "secret_path": "protected_file:/run/secrets/synthetic-mail-test",
            "fingerprint": "a" * 64,
            "owner": "automated-test",
        })
        values = {
            "email_address": "mailbox-gate@invalid.example",
            "provider": "synthetic_mail_sink",
            "external_mailbox_id": "synthetic-mailbox-1",
            "aliases": ["alias-gate@invalid.example"],
            "provisioning_state": "awaiting_activation",
            "credential_reference": credential.id,
        }
        self.env["codestra.company.mailbox"].create(values)
        with self.assertRaises(UniqueViolation):
            self.env["codestra.company.mailbox"].create({
                **values, "external_mailbox_id": "synthetic-mailbox-2",
            })
        with self.assertRaises(ValidationError):
            self.env["codestra.company.mailbox"].create({
                **values,
                "email_address": "other-gate@invalid.example",
                "external_mailbox_id": "synthetic-mailbox-3",
                "aliases": ["not-an-email"],
            })

    def test_audit_is_append_only(self):
        request = self.env["codestra.provisioning.request"].create(
            self._request_values("audit-request")
        )
        audit = self.env["codestra.provisioning.audit"].create({
            "request_id": request.id,
            "event_type": "request.created",
            "actor_system": "odoo",
            "correlation_id": request.correlation_id,
            "result": "accepted",
        })
        with self.assertRaises(AccessError):
            audit.write({"result": "changed"})
        with self.assertRaises(AccessError):
            audit.unlink()

    def test_request_keys_are_immutable_and_deterministic(self):
        values = self._request_values()
        values.pop("idempotency_key")
        request = self.env["codestra.provisioning.request"].create(values)
        self.assertEqual(len(request.idempotency_key), 64)
        with self.assertRaises(ValidationError):
            request.write({"correlation_id": "changed"})
        with self.assertRaises(ValidationError):
            request.write({"idempotency_key": "changed"})

    def test_default_role_templates_are_scoped_and_least_privilege(self):
        templates = self.env["codestra.role.template"].search([
            ("business_unit_id", "=", self.unit.id),
            ("code", "in", [
                "AGENT", "CLOSER", "SUPERVISOR", "QA_REVIEWER",
                "CAMPAIGN_MANAGER", "COMPLIANCE", "AUDITOR",
                "SYSTEM_ADMIN", "INTEGRATION_SERVICE",
            ]),
        ])
        self.assertEqual(len(templates), 9)
        agent = templates.filtered(lambda template: template.code == "AGENT")
        supervisor = templates.filtered(lambda template: template.code == "SUPERVISOR")
        self.assertFalse(agent.odoo_group_ids)
        self.assertFalse(agent.allows_monitoring)
        self.assertFalse(agent.allows_transfer)
        self.assertTrue(supervisor.allows_monitoring)
        self.assertFalse(supervisor.allows_transfer)

    def test_fail_closed_safety_flags(self):
        parameters = self.env["ir.config_parameter"].sudo()
        for flag in (
            "send_events", "production_callbacks_enabled",
            "vicidial_writes_enabled", "external_dial_enabled",
            "transfers_enabled", "n8n_production_workflows_enabled",
            "webrtc_production_routes_enabled", "allow_live_email",
            "allow_live_sms", "allow_live_calls",
            "allow_campaign_activation",
        ):
            self.assertEqual(
                parameters.get_param("codestra.provisioning.%s" % flag),
                "false",
            )
        self.assertTrue(
            self.env["codestra.provisioning.request"].assert_safe_mode()
        )
        parameters.set_param(
            "codestra.provisioning.vicidial_writes_enabled", "true"
        )
        with self.assertRaises(UserError):
            self.env["codestra.provisioning.request"].assert_safe_mode()

    def test_reservation_and_steps_are_idempotent(self):
        values = self._request_values("prepare-request")
        values.update({
            "needs_company_email": True,
            "needs_sip_endpoint": True,
        })
        request = self.env["codestra.provisioning.request"].create(values)
        request.state = "approved"
        request.action_reserve_identifiers()
        first_reservations = request.env[
            "codestra.identifier.reservation"
        ].search_count([("request_id", "=", request.id)])
        first_steps = len(request.step_ids)
        request.state = "failed"
        request.action_reserve_identifiers()
        self.assertEqual(
            request.env["codestra.identifier.reservation"].search_count([
                ("request_id", "=", request.id),
            ]),
            first_reservations,
        )
        self.assertEqual(len(request.step_ids), first_steps)
        self.assertTrue(request.employee_id.codestra_employee_number)

    def test_partial_failure_is_sanitized_and_retry_is_targeted(self):
        request = self.env["codestra.provisioning.request"].create(
            self._request_values("partial-failure")
        )
        request._ensure_steps()
        failed = request.step_ids[0]
        untouched = request.step_ids[1]
        failed.mark_failed(
            "provider.failure", RuntimeError("credential=redacted-marker")
        )
        self.assertEqual(request.state, "partially_provisioned")
        self.assertNotIn("redacted-marker", failed.last_error_sanitized)
        self.assertEqual(untouched.state, "pending")
        request.action_retry_failed_steps()
        self.assertEqual(failed.state, "retry_scheduled")
        self.assertEqual(untouched.state, "pending")

    def test_suspension_and_termination_lifecycle(self):
        self.employee.codestra_employee_number = "SYN-2026-00001"
        suspend_request = self.env["codestra.provisioning.request"].create({
            **self._request_values("suspend-request"),
            "request_type": "suspend",
        })
        link = self.env["codestra.identity.link"].create({
            "employee_id": self.employee.id,
            "system": "keycloak",
            "provider": "staging",
            "external_id": "synthetic-keycloak",
            "business_unit_id": self.unit.id,
            "state": "active",
        })
        with patch.object(
            ProvisioningRequest,
            "_dispatch_lifecycle_to_service",
            autospec=True,
            return_value={"state": "completed"},
        ) as dispatch:
            suspend_request.action_suspend()
        dispatch.assert_called_once_with(suspend_request, "suspend")
        self.assertEqual(link.state, "suspended")
        self.assertEqual(self.employee.provisioning_state, "suspended")
        reactivate_request = self.env["codestra.provisioning.request"].create({
            **self._request_values("reactivate-request"),
            "request_type": "reactivate",
        })
        with patch.object(
            ProvisioningRequest,
            "_dispatch_lifecycle_to_service",
            autospec=True,
            return_value={"state": "completed"},
        ) as dispatch:
            reactivate_request.action_reactivate()
        dispatch.assert_called_once_with(reactivate_request, "reactivate")
        self.assertEqual(link.state, "active")
        self.assertEqual(self.employee.provisioning_state, "active")
        terminate_request = self.env["codestra.provisioning.request"].create({
            **self._request_values("terminate-request"),
            "request_type": "terminate",
        })
        with patch.object(
            ProvisioningRequest,
            "_dispatch_lifecycle_to_service",
            autospec=True,
            return_value={"state": "completed"},
        ) as dispatch:
            terminate_request.action_terminate()
        dispatch.assert_called_once_with(terminate_request, "terminate")
        self.assertEqual(link.state, "terminated")
        self.assertEqual(terminate_request.state, "terminated")
        self.assertEqual(self.employee.provisioning_state, "terminated")

    def test_reconciliation_projects_aligned_state(self):
        self.employee.codestra_employee_number = "SYN-2026-00002"
        request = self.env["codestra.provisioning.request"].create(
            self._request_values("reconciliation-request")
        )
        link = self.env["codestra.identity.link"].create({
            "employee_id": self.employee.id,
            "system": "keycloak",
            "provider": "staging",
            "external_id": "synthetic-reconciliation-keycloak",
            "business_unit_id": self.unit.id,
            "state": "active",
            "drift_state": "privilege_drift",
        })
        with patch.object(
            PrivateProvisioningService,
            "request",
            autospec=True,
            return_value={"state": "aligned", "systems": []},
        ) as service_request:
            request.action_reconcile()
        self.assertEqual(request.drift_state, "aligned")
        self.assertTrue(request.last_reconciled_at)
        self.assertEqual(link.drift_state, "aligned")
        service_request.assert_called_once()

    def test_role_conflict_blocks_approval(self):
        conflict = self.env["codestra.role.template"].create({
            "name": "Conflicting Role",
            "code": "SYN_CONFLICT",
            "business_unit_id": self.unit.id,
            "company_id": self.env.company.id,
        })
        template = self.env["codestra.role.template"].create({
            "name": "Conflict Holder",
            "code": "SYN_CONFLICT_HOLDER",
            "business_unit_id": self.unit.id,
            "company_id": self.env.company.id,
            "conflicting_template_ids": [(6, 0, conflict.ids)],
        })
        request = self.env["codestra.provisioning.request"].create({
            **self._request_values("role-conflict"),
            "role_template_id": template.id,
            "operational_approved": True,
            "it_approved": True,
        })
        request.state = "pending_approval"
        with self.assertRaises(UserError):
            request.action_approve()

    def test_service_callback_application_is_idempotent(self):
        provision_request = self.env["codestra.provisioning.request"].create(
            self._request_values("callback-request")
        )
        provision_request._ensure_steps()
        step = provision_request.step_ids[0]
        payload = {
            "event_id": "callback-event-identity-0001",
            "request_id": provision_request.id,
            "correlation_id": provision_request.correlation_id,
            "state": "verification",
            "step_results": [{
                "target_system": step.target_system,
                "operation": step.operation,
                "state": "verified",
                "external_id": "protected-external-id",
                "evidence_hash": "a" * 64,
            }],
            "timestamp": "2026-07-26T00:00:00Z",
        }
        self.assertEqual(
            self.env["codestra.provisioning.request"].apply_service_callback(
                payload
            )["state"],
            "accepted",
        )
        self.assertEqual(step.state, "verified")
        self.assertEqual(step.verification_state, "verified")
        self.assertEqual(
            self.env["codestra.provisioning.request"].apply_service_callback(
                payload
            )["state"],
            "replayed",
        )

    def test_business_unit_campaign_isolation_constraint(self):
        other_unit = self.env["call.center.business.unit"].create({
            "name": "Other Unit", "code": "OTHER",
        })
        campaign = self.env["call.center.campaign"].create({
            "name": "Other Campaign",
            "code": "OTHER-CAMPAIGN",
            "business_unit_id": other_unit.id,
        })
        with self.assertRaises(ValidationError):
            self.env["codestra.provisioning.request"].create({
                **self._request_values("cross-campaign"),
                "campaign_ids": [(6, 0, campaign.ids)],
            })

    def test_non_approver_cannot_approve(self):
        group = self.env.ref(
            "codestra_identity_provisioning.group_provisioning_user"
        )
        user = self.env["res.users"].create({
            "name": "Provisioning Requester",
            "login": "provisioning.requester",
            "group_ids": [(6, 0, group.ids)],
            "call_center_business_unit_ids": [(6, 0, self.unit.ids)],
            "call_center_default_business_unit_id": self.unit.id,
        })
        request = self.env["codestra.provisioning.request"].create(
            self._request_values("rbac-approval")
        )
        request.state = "pending_approval"
        with self.assertRaises(AccessError):
            request.with_user(user).action_approve()

    def test_record_rule_hides_other_business_unit(self):
        group = self.env.ref(
            "codestra_identity_provisioning.group_provisioning_user"
        )
        other_unit = self.env["call.center.business.unit"].create({
            "name": "Rule Other Unit", "code": "RULE-OTHER",
        })
        user = self.env["res.users"].create({
            "name": "Scoped Provisioner",
            "login": "scoped.provisioner",
            "group_ids": [(6, 0, group.ids)],
            "call_center_business_unit_ids": [(6, 0, other_unit.ids)],
            "call_center_default_business_unit_id": other_unit.id,
        })
        request = self.env["codestra.provisioning.request"].create(
            self._request_values("record-rule")
        )
        self.assertNotIn(
            request,
            self.env["codestra.provisioning.request"].with_user(user).search([]),
        )

    def test_new_internal_user_receives_primary_role_default(self):
        user = self.env["res.users"].create({
            "name": "Synthetic Default Role User",
            "login": "synthetic.default.role",
        })
        self.assertEqual(user.call_center_primary_role, "non_operational")

    def test_duplicate_login_is_rejected(self):
        values = {
            "name": "Synthetic Unique Login",
            "login": "synthetic.unique.login",
        }
        self.env["res.users"].create(values)
        with self.assertRaises(ValidationError):
            self.env["res.users"].create(values)

    def test_identity_menu_action_and_administrator_access(self):
        root = self.env.ref(
            "codestra_identity_provisioning.menu_identity_provisioning_root"
        )
        requests = self.env.ref(
            "codestra_identity_provisioning.menu_provisioning_requests"
        )
        action = self.env.ref(
            "codestra_identity_provisioning.action_provisioning_requests"
        )
        administrator = self.env.ref("base.user_admin")
        self.assertEqual(root.name, "Identity Provisioning")
        self.assertEqual(requests.name, "Provisioning Requests")
        self.assertEqual(requests.parent_id, root)
        self.assertEqual(requests.action, action)
        self.assertEqual(action.res_model, "codestra.provisioning.request")
        self.assertEqual(action.view_mode, "list,form")
        self.assertTrue(
            administrator.has_group(
                "codestra_identity_provisioning.group_provisioning_user"
            )
        )

    def test_unauthorized_internal_user_cannot_access_identity_menu(self):
        user = self.env["res.users"].create({
            "name": "Synthetic Unauthorized User",
            "login": "synthetic.unauthorized",
        })
        root = self.env.ref(
            "codestra_identity_provisioning.menu_identity_provisioning_root"
        )
        request_model = self.env["codestra.provisioning.request"].with_user(user)
        self.assertNotIn(
            root.id,
            self.env["ir.ui.menu"].with_user(user)._visible_menu_ids(),
        )
        with self.assertRaises(AccessError):
            request_model.check_access("read")

    def test_campaign_dropdown_derives_authoritative_scope(self):
        campaign = self.env["call.center.campaign"].create({
            "name": "Synthetic Campaign",
            "code": "SYN-CAMPAIGN",
            "business_unit_id": self.unit.id,
            "team_ids": [(6, 0, self.team.ids)],
            "supervisor_ids": [(6, 0, self.supervisor.ids)],
        })
        provision = self.env["codestra.provisioning.request"].new({
            "primary_campaign_id": campaign.id,
        })
        provision._onchange_primary_campaign_id()
        self.assertEqual(provision.business_unit_id, self.unit)
        self.assertEqual(provision.campaign_ids._origin.ids, campaign.ids)
        self.assertEqual(provision.operational_team_id, self.team)
        self.assertEqual(provision.department_id, self.department)
        self.assertEqual(provision.supervisor_id, self.supervisor)

    def test_monitoring_snapshot_is_secret_free(self):
        self.employee.codestra_employee_number = "SYN-MON-0001"
        campaign = self.env["call.center.campaign"].create({
            "name": "Synthetic Monitoring Campaign",
            "code": "SYN-MONITOR",
            "business_unit_id": self.unit.id,
        })
        provision = self.env["codestra.provisioning.request"].create({
            **self._request_values("monitoring-snapshot"),
            "primary_campaign_id": campaign.id,
            "campaign_ids": [(6, 0, campaign.ids)],
            "state": "active",
            "employment_status": "active",
        })
        for system, username in (
            ("keycloak", "synthetic.keycloak"),
            ("vicidial", "syn00001"),
        ):
            self.env["codestra.identity.link"].create({
                "employee_id": self.employee.id,
                "system": system,
                "provider": "synthetic",
                "external_id": "%s-external" % system,
                "external_username": username,
                "business_unit_id": self.unit.id,
                "state": "active",
            })
        self.env["codestra.identity.link"].create({
            "employee_id": self.employee.id,
            "system": "sip",
            "provider": "synthetic",
            "external_id": "sip-external",
            "extension": "6198",
            "business_unit_id": self.unit.id,
            "state": "active",
        })
        self.assertFalse(self.monitoring_user.has_group("hr.group_hr_user"))
        self.assertFalse(self.monitoring_user.has_group("base.group_system"))
        result = provision.with_user(self.monitoring_user).monitoring_snapshot(
            campaign_code="SYN-MONITOR"
        )
        self.assertEqual(result["count"], 1)
        agent = result["agents"][0]
        self.assertEqual(agent["employee_id"], "SYN-MON-0001")
        self.assertEqual(agent["display_name"], self.employee.name)
        self.assertEqual(agent["vicidial_username"], "syn00001")
        self.assertEqual(agent["campaigns"][0]["code"], "SYN-MONITOR")
        self.assertTrue(agent["is_active"])
        self.assertFalse({"password", "token", "sip_secret"} & set(agent))

    def test_monitoring_filters_legacy_campaign_before_limit(self):
        campaign = self.env["call.center.campaign"].create({
            "name": "Legacy Monitoring Campaign", "code": "SYN-LEGACY-MON",
            "business_unit_id": self.unit.id,
        })
        self.env["codestra.provisioning.request"].create(
            self._request_values("monitoring-unrelated-first")
        )
        employee = self.env["hr.employee"].create({"name": "Legacy Employee"})
        provision = self.env["codestra.provisioning.request"].create({
            **self._request_values("monitoring-legacy"),
            "employee_id": employee.id,
            "campaign_ids": [(6, 0, campaign.ids)],
        })
        self.assertFalse(provision.primary_campaign_id)
        result = provision.with_user(self.monitoring_user).monitoring_snapshot(
            campaign_code=campaign.code, limit=1
        )
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["agents"][0]["employee_id"], str(employee.id))
        self.assertEqual(result["agents"][0]["campaigns"][0]["code"], campaign.code)
        self.assertFalse(result["agents"][0]["is_active"])

    def test_monitoring_respects_request_scope_and_requires_permission(self):
        provision = self.env["codestra.provisioning.request"].create(
            self._request_values("monitoring-rules")
        )
        self.assertEqual(provision.with_user(self.monitoring_user).monitoring_snapshot()["count"], 1)
        self.monitoring_user.call_center_business_unit_ids = [(5, 0, 0)]
        self.assertEqual(provision.with_user(self.monitoring_user).monitoring_snapshot()["count"], 0)
        self.monitoring_user.group_ids = [(6, 0, self.env.ref("base.group_user").ids)]
        with self.assertRaises(AccessError):
            provision.with_user(self.monitoring_user).monitoring_snapshot()

    def test_monitoring_does_not_reuse_other_unit_identity(self):
        provision = self.env["codestra.provisioning.request"].create({
            **self._request_values("monitoring-link-scope"),
            "state": "active", "employment_status": "active",
        })
        other_unit = self.env["call.center.business.unit"].create({
            "name": "Other Identity Unit", "code": "OTHER-IDENTITY",
        })
        # Even a monitor assigned to both units must not report an identity
        # from the other unit as this request's active identity.
        self.monitoring_user.call_center_business_unit_ids = [(4, other_unit.id)]
        for system in ("keycloak", "vicidial"):
            self.env["codestra.identity.link"].create({
                "employee_id": self.employee.id, "system": system,
                "external_id": "other-unit-" + system,
                "external_username": "other-unit-user",
                "business_unit_id": other_unit.id, "state": "active",
            })
        result = provision.with_user(self.monitoring_user).monitoring_snapshot()
        self.assertEqual(result["count"], 1)
        self.assertFalse(result["agents"][0]["is_active"])
        self.assertFalse(result["agents"][0]["keycloak_username"])
        self.assertFalse(result["agents"][0]["vicidial_username"])

    def test_campaign_change_clears_ambiguous_and_empty_assignments(self):
        campaign = self.env["call.center.campaign"].create({
            "name": "Mapped Campaign", "code": "SYN-MAPPED",
            "business_unit_id": self.unit.id,
            "team_ids": [(6, 0, self.team.ids)],
            "supervisor_ids": [(6, 0, self.supervisor.ids)],
        })
        other_team = self.team.copy({"name": "Other Team", "code": "SYN-T2"})
        ambiguous = campaign.copy({
            "name": "Ambiguous Campaign", "code": "SYN-AMBIGUOUS",
            "team_ids": [(6, 0, (self.team | other_team).ids)],
        })
        empty = campaign.copy({
            "name": "Empty Campaign", "code": "SYN-EMPTY",
            "team_ids": [(5, 0, 0)], "supervisor_ids": [(5, 0, 0)],
        })
        pool = self.env["codestra.extension.pool"].create({
            "name": "Mapped Pool", "code": "SYN-MAPPED-POOL",
            "business_unit_id": self.unit.id, "start_extension": 6102,
            "end_extension": 6110, "context": "synthetic", "active": True,
        })
        provision = self.env["codestra.provisioning.request"].new({
            "primary_campaign_id": campaign.id,
        })
        for target in (ambiguous, empty, self.env["call.center.campaign"]):
            with self.subTest(target=target.code or "cleared"):
                pool.active = True
                provision.primary_campaign_id = campaign
                provision._onchange_primary_campaign_id()
                self.assertEqual(provision.operational_team_id, self.team)
                self.assertEqual(provision.extension_pool_id, pool)
                pool.active = False
                provision.primary_campaign_id = target
                provision._onchange_primary_campaign_id()
                for field in ("operational_team_id", "department_id", "supervisor_id", "extension_pool_id"):
                    self.assertFalse(provision[field], field)
        self.assertFalse(provision.campaign_ids)
        self.assertFalse(provision.calling_hours_policy_id)

    def test_campaign_change_clears_multiple_supervisors_and_pools(self):
        second_supervisor = self.supervisor.copy({"login": "synthetic.second.supervisor"})
        campaign = self.env["call.center.campaign"].create({
            "name": "Multiple Choices", "code": "SYN-MULTIPLE",
            "business_unit_id": self.unit.id,
            "team_ids": [(6, 0, self.team.ids)],
            "supervisor_ids": [(6, 0, self.supervisor.ids)],
        })
        pool = self.env["codestra.extension.pool"].create({
            "name": "First Pool", "code": "SYN-FIRST-POOL",
            "business_unit_id": self.unit.id, "start_extension": 6120,
            "end_extension": 6130, "context": "synthetic", "active": True,
        })
        provision = self.env["codestra.provisioning.request"].new({"primary_campaign_id": campaign.id})
        provision._onchange_primary_campaign_id()
        self.assertEqual(provision.supervisor_id, self.supervisor)
        self.assertEqual(provision.extension_pool_id, pool)
        self.team.supervisor_ids = [(4, second_supervisor.id)]
        campaign.supervisor_ids = [(4, second_supervisor.id)]
        pool.copy({"name": "Second Pool", "code": "SYN-SECOND-POOL"})
        provision._onchange_primary_campaign_id()
        self.assertEqual(provision.operational_team_id, self.team)
        self.assertFalse(provision.supervisor_id)
        self.assertFalse(provision.extension_pool_id)

    def test_primary_campaign_rejects_team_from_same_unit(self):
        other_team = self.team.copy({"name": "Different Campaign Team", "code": "SYN-T3"})
        campaign = self.env["call.center.campaign"].create({
            "name": "Different Team Campaign", "code": "SYN-DIFFERENT-TEAM",
            "business_unit_id": self.unit.id,
            "team_ids": [(6, 0, other_team.ids)],
        })
        with self.assertRaisesRegex(ValidationError, "outside the primary campaign"), self.cr.savepoint():
            self.env["codestra.provisioning.request"].create({
                **self._request_values("campaign-team-mismatch"),
                "primary_campaign_id": campaign.id,
                "campaign_ids": [(6, 0, campaign.ids)],
            })
