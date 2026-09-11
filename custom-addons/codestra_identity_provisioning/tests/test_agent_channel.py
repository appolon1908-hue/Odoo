from datetime import date

from psycopg2.errors import UniqueViolation

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
        cls.legacy_unit = cls.campaign_a.legacy_campaign_id.business_unit_id

        cls.requester = cls._create_user(
            "Agent Channel Requester",
            "agent-channel-requester@example.invalid",
            ["codestra_cc_security.group_cc_global_administrator"],
        )
        cls.approver = cls.requester
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
        pool = self.env["codestra.extension.pool"].create({
            "name": "Blocked Pool",
            "code": "AGCH-BLK",
            "business_unit_id": self.legacy_unit.id,
            "start_extension": 6000,
            "end_extension": 6200,
            "context": "codestra_restricted",
            "active": True,
        })
        blocked_assignment = self.env["codestra.extension.assignment"].create({
            "pool_id": pool.id,
            "extension": "6101",
            "employee_id": self.other_employee.id,
            "request_id": self.request.id,
            "state": "reserved",
            "reserved_at": fields.Datetime.now(),
        })
        Channel = self.env["codestra.agent.channel"].with_user(self.super_admin)
        with self.assertRaises(ValidationError):
            Channel.create(
                self._channel_values(
                    "phone",
                    employee_id=self.other_employee.id,
                    membership_id=False,
                    extension_assignment_id=blocked_assignment.id,
                )
            )

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
        channel.write({"state": "effective"})
        self.assertTrue(channel.campaign_id)
        self.assertTrue(channel.supervisor_id)
        self.assertTrue(channel.effective_access)

    def test_disabling_desired_enabled_clears_effective_access(self):
        Channel = self.env["codestra.agent.channel"].with_user(self.super_admin)
        channel = Channel.create(
            self._channel_values(
                "phone",
                desired_enabled=True,
                state="effective",
                extension_assignment_id=self.assignment.id,
            )
        )
        self.assertTrue(channel.effective_access)
        channel.write({"desired_enabled": False})
        self.assertFalse(channel.effective_access)

    def test_email_channel_can_be_effective_without_an_extension(self):
        Channel = self.env["codestra.agent.channel"].with_user(self.super_admin)
        channel = Channel.create(
            self._channel_values("email", desired_enabled=True, state="effective")
        )
        self.assertTrue(channel.effective_access)

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
        channel.with_user(self.provisioning_service_user).write(
            {"state": "provisioning", "external_system": "vicidial"}
        )
        with self.assertRaises(AccessError):
            channel.with_user(self.provisioning_service_user).write(
                {"desired_enabled": True}
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
