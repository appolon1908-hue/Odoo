from datetime import date

from psycopg2.errors import CheckViolation, UniqueViolation

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestAgentChannel(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["cc.business.unit"]._adopt_legacy_records()
        cls.Campaign = cls.env["cc.campaign"].with_context(active_test=False)
        cls.identity_managed = "cc.identity.outbox" in cls.env
        cls.campaign_a = cls.Campaign.search([("code", "=", "COD-WEB-OUT")], limit=1)
        cls.campaign_a.ensure_one()
        # "active" is unconditionally blocked in this staging environment
        # (see CcCampaign._check_workspace); "staging_ready" is in the same
        # SAFE_CAMPAIGN_LIFECYCLE_STATES set and is actually reachable here.
        cls.campaign_a.write({"lifecycle_state": "staging_ready"})
        cls.legacy_unit = cls.campaign_a.legacy_campaign_id.business_unit_id

        cls.requester = cls._create_user(
            "Agent Channel Requester",
            "agent-channel-requester@example.invalid",
            ["codestra_cc_security.group_cc_global_administrator"],
        )
        cls.approver = cls._create_user(
            "Agent Channel Approver",
            "agent-channel-approver@example.invalid",
            ["codestra_cc_security.group_cc_global_administrator"],
        )
        cls.identity_service = cls._create_user(
            "Agent Channel Identity Service",
            "agent-channel-identity-service@example.invalid",
            ["base.group_user", "codestra_identity_provisioning.group_provisioning_service"],
        )
        cls.super_admin = cls._create_user(
            "Agent Channel Super Admin",
            "agent-channel-super-admin@example.invalid",
            ["codestra_identity_provisioning.group_provisioning_global_super_admin"],
        )
        cls.provisioning_service_user = cls._create_user(
            "Agent Channel Provisioning Service",
            "agent-channel-provisioning-service@example.invalid",
            ["base.group_user", "codestra_identity_provisioning.group_provisioning_service"],
        )
        cls.agent_user = cls._create_user(
            "Agent Channel Agent",
            "agent-channel-agent@example.invalid",
            ["codestra_cc_security.group_cc_campaign_agent"],
        )
        cls.supervisor_user = cls._create_user(
            "Agent Channel Supervisor",
            "agent-channel-supervisor@example.invalid",
            ["codestra_cc_security.group_cc_campaign_supervisor"],
        )

        cls.agent_membership = cls._activate_membership(
            cls.agent_user, cls.campaign_a, "AGENT-CHANNEL-AGENT", "agent"
        )
        cls.employee = cls.agent_membership.employee_id
        cls.supervisor_membership = cls._activate_membership(
            cls.supervisor_user,
            cls.campaign_a,
            "AGENT-CHANNEL-SUPERVISOR",
            "supervisor",
            is_primary_supervisor=True,
        )
        cls.campaign_a.invalidate_recordset(["primary_supervisor_membership_id"])
        assert cls.campaign_a.primary_supervisor_membership_id == cls.supervisor_membership

        cls.department = cls.env["call.center.department"].create({
            "name": "Agent Channel Operations",
            "code": "AGCH-OPS",
            "business_unit_id": cls.legacy_unit.id,
        })
        cls.team = cls.env["call.center.team"].create({
            "name": "Agent Channel Team",
            "code": "AGCH-T1",
            "business_unit_id": cls.legacy_unit.id,
            "department_id": cls.department.id,
            "supervisor_ids": [(6, 0, cls.supervisor_user.ids)],
        })
        cls.role_template = cls.env["codestra.role.template"].create({
            "name": "Agent Channel Agent Role",
            "code": "AGCH_AGENT",
            "business_unit_id": cls.legacy_unit.id,
            "company_id": cls.env.company.id,
        })
        cls.request = cls.env["codestra.provisioning.request"].create({
            "request_type": "onboard",
            "employee_id": cls.employee.id,
            "supervisor_id": cls.supervisor_user.id,
            "company_id": cls.env.company.id,
            "business_unit_id": cls.legacy_unit.id,
            "department_id": cls.department.id,
            "operational_team_id": cls.team.id,
            "role_template_id": cls.role_template.id,
            "start_date": date.today(),
            "idempotency_key": "agent-channel-request",
            "needs_sip_endpoint": True,
        })
        cls.extension_pool = cls.env["codestra.extension.pool"].create({
            "name": "Agent Channel Pool",
            "code": "AGCH-EXT",
            "business_unit_id": cls.legacy_unit.id,
            "start_extension": 7400,
            "end_extension": 7499,
            "context": "codestra_restricted",
            "active": True,
        })
        cls.assignment = cls.env["codestra.extension.assignment"].create({
            "pool_id": cls.extension_pool.id,
            "extension": "7401",
            "employee_id": cls.employee.id,
            "request_id": cls.request.id,
            "state": "committed",
            "reserved_at": fields.Datetime.now(),
            "committed_at": fields.Datetime.now(),
        })

        cls.other_employee = cls.env["hr.employee"].create({"name": "Other Employee"})

    @classmethod
    def _create_user(cls, name, login, group_xmlids):
        groups = cls.env["res.groups"].browse(
            [cls.env.ref(xmlid).id for xmlid in group_xmlids]
        )
        return cls.env["res.users"].create(
            {"name": name, "login": login, "group_ids": [(6, 0, groups.ids)]}
        )

    @classmethod
    def _activate_membership(cls, user, campaign, ticket, role, is_primary_supervisor=False):
        employee = cls.env["hr.employee"].create(
            {"name": user.name, "user_id": user.id, "company_id": cls.env.company.id}
        )
        values = {
            "user_id": user.id,
            "employee_id": employee.id,
            "campaign_id": campaign.id,
            "role": role,
            "is_primary_supervisor": is_primary_supervisor,
            "requested_by_id": cls.requester.id,
            "source_ticket": ticket,
            "starts_at": fields.Datetime.now(),
        }
        if not cls.identity_managed:
            values["state"] = "pending_sync"
        membership = cls.env["cc.campaign.membership"].with_user(cls.requester).create(values)
        if cls.identity_managed:
            membership.with_user(cls.requester).action_submit_identity()
            operation = membership.with_user(cls.approver).action_approve_identity()
            operation.with_user(cls.identity_service).action_record_readback(
                {
                    target: {"status": "matched", "evidence_hash": "a" * 64}
                    for target in operation.required_targets
                },
                f"staging://agent-channel/{ticket.lower()}",
            )
        membership.with_user(cls.approver).action_activate()
        return membership

    def _channel_values(self, channel_type, **extra):
        values = {
            "employee_id": self.employee.id,
            "membership_id": self.agent_membership.id,
            "channel_type": channel_type,
        }
        values.update(extra)
        return values

    def test_create_one_channel_per_type(self):
        Channel = self.env["codestra.agent.channel"].with_user(self.super_admin)
        for channel_type in ("email", "sms", "phone", "webrtc"):
            Channel.create(self._channel_values(channel_type))
        self.assertEqual(
            len(Channel.search([("employee_id", "=", self.employee.id)])), 4
        )

    def test_duplicate_channel_type_rejected(self):
        Channel = self.env["codestra.agent.channel"].with_user(self.super_admin)
        Channel.create(self._channel_values("email"))
        with self.assertRaises(UniqueViolation):
            Channel.create(self._channel_values("email"))

    def test_voice_permissions_rejected_on_email_and_sms(self):
        Channel = self.env["codestra.agent.channel"].with_user(self.super_admin)
        with self.assertRaises(ValidationError):
            Channel.create(self._channel_values("email", incoming_allowed=True))
        with self.assertRaises(ValidationError):
            Channel.create(self._channel_values("sms", outgoing_allowed=True))

    def test_extension_6101_rejected(self):
        # codestra.extension.assignment has its own hard database CHECK
        # constraint excluding extension 6101 (see
        # codestra_identity_provisioning/tests/test_provisioning.py::
        # test_extension_6101_is_hard_excluded) - no assignment with that
        # extension can ever exist to attach to a channel, so
        # CodestraAgentChannel._check_extension_not_6101 is unreachable
        # defense-in-depth, not something with an independent failure path.
        # What's actually testable here is that this lower layer holds.
        pool = self.env["codestra.extension.pool"].create({
            "name": "Blocked Pool",
            "code": "AGCH-BLK",
            "business_unit_id": self.legacy_unit.id,
            "start_extension": 6000,
            "end_extension": 6200,
            "context": "codestra_restricted",
            "active": True,
        })
        with self.assertRaises(CheckViolation):
            self.env["codestra.extension.assignment"].create({
                "pool_id": pool.id,
                "extension": "6101",
                "employee_id": self.other_employee.id,
                "request_id": self.request.id,
                "state": "reserved",
                "reserved_at": fields.Datetime.now(),
            })

    def test_extension_assignment_must_belong_to_same_employee(self):
        Channel = self.env["codestra.agent.channel"].with_user(self.super_admin)
        with self.assertRaises(ValidationError):
            Channel.create(
                self._channel_values(
                    "phone",
                    employee_id=self.other_employee.id,
                    membership_id=False,
                    extension_assignment_id=self.assignment.id,
                )
            )

    def test_effective_access_requires_effective_state_and_committed_extension(self):
        Channel = self.env["codestra.agent.channel"].with_user(self.super_admin)
        channel = Channel.create(
            self._channel_values(
                "phone",
                desired_enabled=True,
                extension_assignment_id=self.assignment.id,
            )
        )
        self.assertFalse(channel.effective_access)
        channel._mark_effective()
        self.assertTrue(channel.campaign_id)
        self.assertTrue(channel.supervisor_id)
        self.assertTrue(channel.effective_access)

    def test_effective_access_requires_membership_sync_and_campaign_lifecycle(self):
        Channel = self.env["codestra.agent.channel"].with_user(self.super_admin)
        channel = Channel.create(
            self._channel_values(
                "email", desired_enabled=True, state="requested"
            )
        )
        channel._mark_effective()
        self.assertTrue(channel.effective_access)

        # effective_access also requires the campaign to be in a safe
        # lifecycle state - moving it out (without touching the governed
        # identity read-back path at all) must clear effective_access too.
        self.campaign_a.write({"lifecycle_state": "draft"})
        channel.invalidate_recordset(["effective_access"])
        self.assertFalse(channel.effective_access)
        self.campaign_a.write({"lifecycle_state": "staging_ready"})
        channel.invalidate_recordset(["effective_access"])
        self.assertTrue(channel.effective_access)

    def test_disabling_desired_enabled_clears_effective_access(self):
        Channel = self.env["codestra.agent.channel"].with_user(self.super_admin)
        channel = Channel.create(
            self._channel_values(
                "phone",
                desired_enabled=True,
                extension_assignment_id=self.assignment.id,
            )
        )
        channel._mark_effective()
        self.assertTrue(channel.effective_access)
        channel.write({"desired_enabled": False})
        self.assertFalse(channel.effective_access)

    def test_email_channel_can_be_effective_without_an_extension(self):
        Channel = self.env["codestra.agent.channel"].with_user(self.super_admin)
        channel = Channel.create(
            self._channel_values("email", desired_enabled=True)
        )
        channel._mark_effective()
        self.assertTrue(channel.effective_access)

    def test_state_cannot_be_written_directly_even_by_super_admin(self):
        Channel = self.env["codestra.agent.channel"].with_user(self.super_admin)
        channel = Channel.create(self._channel_values("email"))
        with self.assertRaises(AccessError):
            channel.write({"state": "effective"})
        with self.assertRaises(ValidationError):
            Channel.create(
                self._channel_values("phone", state="provisioned")
            )

    def test_mark_effective_only_affects_desired_enabled_channels(self):
        Channel = self.env["codestra.agent.channel"].with_user(self.super_admin)
        enabled = Channel.create(
            self._channel_values("email", desired_enabled=True)
        )
        disabled = Channel.create(
            self._channel_values("sms", desired_enabled=False)
        )
        (enabled | disabled)._mark_effective()
        self.assertEqual(enabled.state, "effective")
        self.assertEqual(disabled.state, "requested")

    def test_apply_step_evidence_requires_sha256_hash_on_success(self):
        Channel = self.env["codestra.agent.channel"].with_user(self.super_admin)
        channel = Channel.create(self._channel_values("email"))
        with self.assertRaises(ValidationError):
            channel._apply_step_evidence(verified=True, evidence_hash="not-a-hash")
        with self.assertRaises(ValidationError):
            channel._apply_step_evidence(verified=True, evidence_hash=None)
        channel._apply_step_evidence(
            verified=True,
            evidence_hash="a" * 64,
            external_id="ext-1",
            external_reference="ref-1",
        )
        self.assertEqual(channel.state, "provisioned")
        self.assertEqual(channel.external_id, "ext-1")
        self.assertTrue(channel.last_reconciled_at)

    def test_apply_step_evidence_failure_sets_failed_state(self):
        Channel = self.env["codestra.agent.channel"].with_user(self.super_admin)
        channel = Channel.create(self._channel_values("phone"))
        channel._apply_step_evidence(
            verified=False, error_code="UPSTREAM_TIMEOUT", error_sanitized="timed out"
        )
        self.assertEqual(channel.state, "failed")
        self.assertEqual(channel.last_error_code, "UPSTREAM_TIMEOUT")

    def test_only_super_admin_and_service_can_write(self):
        Channel = self.env["codestra.agent.channel"].with_user(self.super_admin)
        channel = Channel.create(self._channel_values("email"))
        with self.assertRaises(AccessError):
            channel.with_user(self.agent_user).write({"desired_enabled": True})
        with self.assertRaises(AccessError):
            channel.with_user(self.supervisor_user).read(["desired_enabled"])

    def test_service_account_can_only_write_external_status_fields(self):
        Channel = self.env["codestra.agent.channel"].with_user(self.super_admin)
        channel = Channel.create(self._channel_values("phone"))
        # external_system is an allowed field and needs no transition
        # capability; state changes always require the governed path (see
        # test_state_cannot_be_written_directly_even_by_super_admin and
        # test_apply_step_evidence_*), even for the service account.
        channel.with_user(self.provisioning_service_user).write(
            {"external_system": "vicidial"}
        )
        self.assertEqual(channel.external_system, "vicidial")
        with self.assertRaises(AccessError):
            channel.with_user(self.provisioning_service_user).write(
                {"desired_enabled": True}
            )
        with self.assertRaises(AccessError):
            channel.with_user(self.provisioning_service_user).write(
                {"state": "provisioning"}
            )

    def test_super_admin_group_granted_to_known_login(self):
        user = self.env["res.users"].create({
            "name": "Provisioning Owner",
            "login": "appolon1908@gmail.com",
        })
        from odoo.addons.codestra_identity_provisioning.hooks import (
            grant_agent_channel_super_admin,
        )

        grant_agent_channel_super_admin(self.env)
        self.assertTrue(
            user.has_group(
                "codestra_identity_provisioning.group_provisioning_global_super_admin"
            )
        )

    def test_migration_backfill_is_idempotent_and_makes_no_external_call(self):
        import importlib.util
        import pathlib

        module_path = (
            pathlib.Path(__file__).resolve().parents[1]
            / "migrations"
            / "19.0.1.3.0"
            / "post-migration.py"
        )
        spec = importlib.util.spec_from_file_location(
            "codestra_identity_provisioning_post_migration_19_0_1_3_0", module_path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        Channel = self.env["codestra.agent.channel"]
        Channel.search([("employee_id", "=", self.employee.id)]).unlink()

        module.migrate(self.env.cr, "19.0.1.3.0")
        first_count = Channel.search_count([("employee_id", "=", self.employee.id)])
        self.assertEqual(first_count, 4)

        module.migrate(self.env.cr, "19.0.1.3.0")
        second_count = Channel.search_count([("employee_id", "=", self.employee.id)])
        self.assertEqual(second_count, first_count)

        phone_channel = Channel.search([
            ("employee_id", "=", self.employee.id), ("channel_type", "=", "phone"),
        ])
        self.assertTrue(phone_channel.desired_enabled)
        self.assertEqual(phone_channel.extension_assignment_id, self.assignment)
