import uuid

from odoo import SUPERUSER_ID, fields
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestAgentWorkspaceCallOwnership(TransactionCase):
    """An agent with only a Transportation-style campaign membership must
    see and act on only their own call/lead data - never another agent's,
    even though both are plain codestra.vicidial.agent/call records with no
    tenant/campaign linkage of their own beyond agent_id.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.campaign = cls.env["codestra.vicidial.campaign"].create({
            "name": "Transportation", "campaign_id": "TRANSPORT_" + cls._rand(),
            "mode": "test",
        })
        cls.agent_a_user, cls.agent_a = cls._make_agent("A")
        cls.agent_b_user, cls.agent_b = cls._make_agent("B")
        cls.call_a = cls.env["codestra.vicidial.call"].sudo().create({
            "name": "CALL-A-" + cls._rand(),
            "agent_id": cls.agent_a.id,
            "tenant_id": "COD",
            "keycloak_subject": cls.agent_a_user.keycloak_subject,
            "state": "connected",
        })
        cls.call_b = cls.env["codestra.vicidial.call"].sudo().create({
            "name": "CALL-B-" + cls._rand(),
            "agent_id": cls.agent_b.id,
            "tenant_id": "COD",
            "keycloak_subject": cls.agent_b_user.keycloak_subject,
            "state": "connected",
        })

    @staticmethod
    def _rand():
        return uuid.uuid4().hex[:8]

    @classmethod
    def _make_agent(cls, label):
        user = cls.env["res.users"].create({
            "name": "Workspace Agent " + label,
            "login": f"workspace-agent-{label.lower()}-{cls._rand()}@example.invalid",
            "group_ids": [(6, 0, [
                cls.env.ref("codestra_cc_security.group_cc_campaign_agent").id,
                # codestra.vicidial.agent/call's own ACL (access_call_user in
                # codestra_vicidial_crm/security/ir.model.access.csv) grants
                # read to this group specifically - group_cc_campaign_agent
                # alone does not cover this older, separate model family.
                cls.env.ref("codestra_vicidial_crm.group_agent").id,
            ])],
        })
        user.write({
            "codestra_tenant_id": "COD",
            "keycloak_subject": str(uuid.uuid4()),
        })
        agent = cls.env["codestra.vicidial.agent"].create({
            "name": "Workspace Agent " + label,
            "vicidial_user": "workspace.agent." + label.lower() + cls._rand(),
            "odoo_user_id": user.id,
            "phone_login": "71" + cls._rand()[:4],
            "campaign_ids": [(6, 0, [cls.campaign.id])],
        })
        return user, agent

    def test_agent_workspace_domain_scopes_to_own_calls_only(self):
        Call = self.env["codestra.vicidial.call"].with_user(self.agent_a_user)
        own_calls = Call.search([("agent_id.odoo_user_id", "=", self.agent_a_user.id)])
        self.assertEqual(own_calls, self.call_a)
        self.assertNotIn(self.call_b, own_calls)

    def test_agent_can_apply_disposition_to_own_call_only(self):
        disposition = self.env["codestra.vicidial.disposition"].create({
            "name": "Interested", "code": "WS-INT-" + self._rand(),
        })
        self.call_a.with_user(self.agent_a_user).action_apply_workspace_disposition(
            disposition_id=disposition.id, notes="Synthetic wrap-up note",
        )
        self.assertEqual(self.call_a.disposition_id, disposition)
        self.assertEqual(self.call_a.notes, "Synthetic wrap-up note")

    def test_agent_cannot_apply_disposition_to_anothers_call(self):
        disposition = self.env["codestra.vicidial.disposition"].create({
            "name": "Not Interested", "code": "WS-NOTINT-" + self._rand(),
        })
        with self.assertRaises(AccessError):
            self.call_b.with_user(self.agent_a_user).action_apply_workspace_disposition(
                disposition_id=disposition.id,
            )

    def test_disposition_wizard_delegates_to_owner_check(self):
        wizard = self.env["codestra.workspace.disposition.wizard"].with_user(
            self.agent_b_user
        ).create({"call_id": self.call_a.id, "notes": "Should be rejected"})
        with self.assertRaises(AccessError):
            wizard.action_submit()


@tagged("post_install", "-at_install")
class TestAdminConsoleTenantScope(TransactionCase):
    """The Admin Console dashboard is built directly on codestra.tenant, so
    it inherits rule_tenant_scope (codestra_identity_provisioning) without
    any new record rule. This proves that inherited scoping actually holds
    for a tenant_admin, and that KPI tiles compute from real membership
    data rather than being hardcoded.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.super_admin = cls._create_user(
            "Admin Console Super Admin",
            ["codestra_identity_provisioning.group_provisioning_global_super_admin"],
        )
        cls.tenant_a = cls.env["codestra.tenant"].with_user(cls.super_admin).create(
            {"name": "Smith Transport", "code": "AC-TENANT-A-" + uuid.uuid4().hex[:6]}
        )
        cls.tenant_b = cls.env["codestra.tenant"].with_user(cls.super_admin).create(
            {"name": "Ridgeline Logistics", "code": "AC-TENANT-B-" + uuid.uuid4().hex[:6]}
        )
        cls.tenant_admin_user = cls._create_user(
            "Admin Console Tenant Admin",
            ["codestra_identity_provisioning.group_tenant_admin"],
        )
        cls.platform_operator_user = cls._create_user(
            "Admin Console Platform Operator",
            ["codestra_identity_provisioning.group_platform_operator"],
        )
        cls.tenant_admin_identity = cls.env["codestra.platform.user"].with_user(
            SUPERUSER_ID
        ).create({
            "name": "Tenant A Admin Identity",
            "primary_email": "tenant-a-admin-identity-" + uuid.uuid4().hex[:6] + "@example.invalid",
            "tenant_id": cls.tenant_a.id,
            "odoo_access_enabled": True,
            "odoo_user_id": cls.tenant_admin_user.id,
        })
        cls.env["codestra.tenant.membership"].with_user(SUPERUSER_ID).create({
            "platform_user_id": cls.tenant_admin_identity.id,
            "tenant_id": cls.tenant_a.id,
            "role": "tenant_admin",
        })

    @classmethod
    def _create_user(cls, name, group_xmlids):
        groups = cls.env["res.groups"].browse(
            [cls.env.ref(xmlid).id for xmlid in group_xmlids]
        )
        return cls.env["res.users"].create(
            {"name": name, "login": name.lower().replace(" ", ".") + "-"
             + uuid.uuid4().hex[:6] + "@example.invalid",
             "group_ids": [(6, 0, groups.ids)]}
        )

    def test_tenant_admin_sees_only_own_tenant(self):
        visible = self.env["codestra.tenant"].with_user(
            self.tenant_admin_user
        ).search([])
        self.assertIn(self.tenant_a, visible)
        self.assertNotIn(self.tenant_b, visible)

    def test_platform_operator_is_read_only_on_tenants(self):
        with self.assertRaises(AccessError):
            self.tenant_a.with_user(self.platform_operator_user).write(
                {"name": "Renamed by operator"}
            )

    def test_kpi_tiles_reflect_real_campaign_membership_data(self):
        campaign = self.env["cc.campaign"].with_context(active_test=False).search(
            [], limit=1
        )
        # A separate identity from tenant_admin_identity: an active
        # cc.campaign.membership requires its user_id to directly hold the
        # role's matching contact-center group
        # (_check_membership_invariants), which a tenant_admin-only user
        # does not and should not hold.
        agent_user = self._create_user(
            "Admin Console KPI Agent",
            ["codestra_cc_security.group_cc_campaign_agent"],
        )
        agent_identity = self.env["codestra.platform.user"].with_user(
            SUPERUSER_ID
        ).create({
            "name": "Tenant A KPI Agent Identity",
            "primary_email": "tenant-a-kpi-agent-" + uuid.uuid4().hex[:6] + "@example.invalid",
            "tenant_id": self.tenant_a.id,
            "odoo_access_enabled": True,
            "odoo_user_id": agent_user.id,
        })
        employee = self.env["hr.employee"].create({
            "name": agent_user.name,
            "user_id": agent_user.id,
            "company_id": self.env.company.id,
        })
        requester = self._create_user(
            "Admin Console Membership Requester",
            ["codestra_cc_security.group_cc_global_administrator"],
        )
        approver = self._create_user(
            "Admin Console Membership Approver",
            ["codestra_cc_security.group_cc_global_administrator"],
        )
        service = self._create_user(
            "Admin Console Identity Service",
            [
                "base.group_user",
                "codestra_identity_provisioning.group_provisioning_service",
                "codestra_cc_crm.group_cc_crm_service",
            ],
        )
        membership = self.env["cc.campaign.membership"].with_user(requester).create({
            "user_id": agent_user.id,
            "employee_id": employee.id,
            "campaign_id": campaign.id,
            "role": "agent",
            "requested_by_id": requester.id,
            "source_ticket": "ADMIN-CONSOLE-KPI-" + uuid.uuid4().hex[:6],
            "starts_at": fields.Datetime.now(),
        })
        membership.with_user(requester).action_submit_identity()
        operation = membership.with_user(approver).action_approve_identity()
        operation.with_user(service).action_record_readback(
            {
                target: {"status": "matched", "evidence_hash": "a" * 64}
                for target in operation.required_targets
            },
            "staging://admin-console/kpi",
        )
        membership.with_user(approver).action_activate()
        membership.with_user(SUPERUSER_ID).write(
            {"platform_user_id": agent_identity.id}
        )
        self.tenant_a.invalidate_recordset()
        self.assertEqual(self.tenant_a.workspace_active_agent_count, 1)
        self.assertEqual(self.tenant_a.workspace_campaign_count, 1)
        self.assertEqual(self.tenant_a.workspace_drift_count, 0)
