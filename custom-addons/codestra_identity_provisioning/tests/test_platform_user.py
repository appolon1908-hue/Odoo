from psycopg2.errors import UniqueViolation

from odoo import SUPERUSER_ID
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestPlatformUser(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.super_admin = cls._create_user(
            "Platform User Super Admin",
            "platform-user-super-admin@example.invalid",
            ["codestra_identity_provisioning.group_provisioning_global_super_admin"],
        )
        cls.normal_admin = cls._create_user(
            "Platform User Normal Admin",
            "platform-user-normal-admin@example.invalid",
            ["call_center_core.group_call_center_admin"],
        )
        cls.supervisor = cls._create_user(
            "Platform User Supervisor",
            "platform-user-supervisor@example.invalid",
            ["codestra_cc_security.group_cc_campaign_supervisor"],
        )
        cls.tenant = cls.env["codestra.tenant"].with_user(cls.super_admin).create({
            "name": "Synthetic Tenant", "code": "SYN-TENANT",
        })
        cls.other_tenant = cls.env["codestra.tenant"].with_user(cls.super_admin).create({
            "name": "Other Synthetic Tenant", "code": "SYN-OTHER-TENANT",
        })
        cls.platform_admin = cls._create_user(
            "Platform User Platform Admin",
            "platform-user-platform-admin@example.invalid",
            ["codestra_identity_provisioning.group_platform_admin"],
        )
        cls.platform_operator = cls._create_user(
            "Platform User Platform Operator",
            "platform-user-platform-operator@example.invalid",
            ["codestra_identity_provisioning.group_platform_operator"],
        )
        cls.tenant_admin_user = cls._create_user(
            "Platform User Tenant Admin",
            "platform-user-tenant-admin@example.invalid",
            ["codestra_identity_provisioning.group_tenant_admin"],
        )
        cls.tenant_admin_platform_user = cls.env["codestra.platform.user"].with_user(
            SUPERUSER_ID
        ).create({
            "name": "Tenant Admin Identity",
            "primary_email": "tenant-admin-identity@example.invalid",
            "tenant_id": cls.tenant.id,
            "odoo_access_enabled": True,
            "odoo_user_id": cls.tenant_admin_user.id,
        })
        cls.env["codestra.tenant.membership"].with_user(SUPERUSER_ID).create({
            "platform_user_id": cls.tenant_admin_platform_user.id,
            "tenant_id": cls.tenant.id,
            "role": "tenant_admin",
        })

    @classmethod
    def _create_user(cls, name, login, group_xmlids):
        groups = cls.env["res.groups"].browse(
            [cls.env.ref(xmlid).id for xmlid in group_xmlids]
        )
        return cls.env["res.users"].create(
            {"name": name, "login": login, "group_ids": [(6, 0, groups.ids)]}
        )

    def _platform_user_values(self, **extra):
        values = {
            "name": "Standalone Customer",
            "primary_email": "standalone.customer@example.invalid",
            "tenant_id": self.tenant.id,
        }
        values.update(extra)
        return values

    def test_only_super_admin_can_create(self):
        PlatformUser = self.env["codestra.platform.user"]
        with self.assertRaises(AccessError):
            PlatformUser.with_user(self.normal_admin).create(
                self._platform_user_values()
            )
        with self.assertRaises(AccessError):
            PlatformUser.with_user(self.supervisor).create(
                self._platform_user_values()
            )
        user = PlatformUser.with_user(self.super_admin).create(
            self._platform_user_values()
        )
        self.assertTrue(user)

    def test_only_super_admin_can_write(self):
        user = self.env["codestra.platform.user"].with_user(self.super_admin).create(
            self._platform_user_values()
        )
        with self.assertRaises(AccessError):
            user.with_user(self.normal_admin).write({"status": "suspended"})
        with self.assertRaises(AccessError):
            user.with_user(self.supervisor).write({"status": "suspended"})
        user.with_user(self.super_admin).write({"status": "suspended"})
        self.assertEqual(user.status, "suspended")

    def test_odoo_access_disabled_creates_no_res_users(self):
        PlatformUser = self.env["codestra.platform.user"].with_user(self.super_admin)
        user = PlatformUser.create(
            self._platform_user_values(
                primary_email="standalone.phone.only@example.invalid",
                odoo_access_enabled=False,
            )
        )
        user.action_ensure_odoo_access()
        self.assertFalse(user.odoo_user_id)

    def test_odoo_access_enabled_creates_res_users(self):
        PlatformUser = self.env["codestra.platform.user"].with_user(self.super_admin)
        user = PlatformUser.create(
            self._platform_user_values(
                primary_email="standalone.with.access@example.invalid",
                odoo_access_enabled=True,
            )
        )
        user.action_ensure_odoo_access()
        self.assertTrue(user.odoo_user_id)
        self.assertEqual(user.odoo_user_id.login, "standalone.with.access@example.invalid")
        # Idempotent: calling again does not create a second user.
        existing = user.odoo_user_id
        user.action_ensure_odoo_access()
        self.assertEqual(user.odoo_user_id, existing)

    def test_odoo_user_requires_access_enabled(self):
        PlatformUser = self.env["codestra.platform.user"].with_user(self.super_admin)
        enabled_user = PlatformUser.create(
            self._platform_user_values(
                primary_email="linked.enabled@example.invalid",
                odoo_access_enabled=True,
            )
        )
        enabled_user.action_ensure_odoo_access()
        with self.assertRaises(ValidationError):
            enabled_user.write({"odoo_access_enabled": False})

    def test_primary_email_must_be_unique(self):
        PlatformUser = self.env["codestra.platform.user"].with_user(self.super_admin)
        PlatformUser.create(self._platform_user_values())
        with self.assertRaises(UniqueViolation):
            PlatformUser.create(self._platform_user_values())

    def test_keycloak_status_reflects_subject_presence(self):
        user = self.env["codestra.platform.user"].with_user(self.super_admin).create(
            self._platform_user_values()
        )
        self.assertEqual(user.keycloak_status, "not_ready")
        user.write({"keycloak_subject": "kc-subject-1"})
        self.assertEqual(user.keycloak_status, "ready")

    def test_suspend_and_reactivate_require_super_admin_and_correct_state(self):
        user = self.env["codestra.platform.user"].with_user(self.super_admin).create(
            self._platform_user_values()
        )
        with self.assertRaises(AccessError):
            user.with_user(self.normal_admin).action_suspend()

        user.with_user(self.super_admin).action_suspend()
        self.assertEqual(user.status, "suspended")

        with self.assertRaises(AccessError):
            user.with_user(self.supervisor).action_reactivate()

        user.with_user(self.super_admin).action_reactivate()
        self.assertEqual(user.status, "active")

        with self.assertRaises(ValidationError):
            user.with_user(self.super_admin).action_reactivate()

    def test_platform_admin_group_alone_has_full_authority(self):
        PlatformUser = self.env["codestra.platform.user"].with_user(self.platform_admin)
        user = PlatformUser.create(self._platform_user_values(
            primary_email="platform-admin-created@example.invalid",
        ))
        user.write({"name": "Renamed By Platform Admin"})
        self.assertEqual(user.name, "Renamed By Platform Admin")

    def test_platform_operator_may_change_status_only(self):
        user = self.env["codestra.platform.user"].with_user(self.super_admin).create(
            self._platform_user_values(primary_email="operator-scoped@example.invalid")
        )
        user.with_user(self.platform_operator).action_suspend()
        self.assertEqual(user.status, "suspended")
        with self.assertRaises(AccessError):
            user.with_user(self.platform_operator).write({"name": "Operator Renamed"})

    def test_tenant_admin_may_write_within_scope_but_not_restricted_fields(self):
        user = self.env["codestra.platform.user"].with_user(self.super_admin).create(
            self._platform_user_values(
                primary_email="tenant-admin-scoped@example.invalid",
                tenant_id=self.tenant.id,
            )
        )
        user.with_user(self.tenant_admin_user).write({"name": "Tenant Admin Renamed"})
        self.assertEqual(user.name, "Tenant Admin Renamed")
        with self.assertRaises(AccessError):
            user.with_user(self.tenant_admin_user).write({"platform_role": "platform_admin"})

    def test_tenant_admin_cannot_write_another_tenants_user(self):
        user = self.env["codestra.platform.user"].with_user(self.super_admin).create(
            self._platform_user_values(
                primary_email="other-tenant-scoped@example.invalid",
                tenant_id=self.other_tenant.id,
            )
        )
        with self.assertRaises(AccessError):
            user.with_user(self.tenant_admin_user).write({"name": "Should Not Work"})

    def test_platform_role_sync_assigns_and_removes_odoo_group(self):
        admin_group = self.env.ref("codestra_identity_provisioning.group_platform_admin")
        operator_group = self.env.ref(
            "codestra_identity_provisioning.group_platform_operator"
        )
        user = self.env["codestra.platform.user"].with_user(self.super_admin).create(
            self._platform_user_values(
                primary_email="role-sync@example.invalid",
                odoo_access_enabled=True,
                platform_role="platform_operator",
            )
        )
        user.action_ensure_odoo_access()
        self.assertIn(operator_group, user.odoo_user_id.group_ids)
        self.assertNotIn(admin_group, user.odoo_user_id.group_ids)

        user.with_user(self.super_admin).write({"platform_role": "platform_admin"})
        self.assertIn(admin_group, user.odoo_user_id.group_ids)
        self.assertNotIn(operator_group, user.odoo_user_id.group_ids)

        user.with_user(self.super_admin).write({"platform_role": "none"})
        self.assertNotIn(admin_group, user.odoo_user_id.group_ids)
        self.assertNotIn(operator_group, user.odoo_user_id.group_ids)

    def test_tenant_membership_tenant_admin_role_requires_platform_admin(self):
        # tenant_admin_user genuinely holds create/write ACL rights on
        # codestra.tenant.membership (group_tenant_admin) - this isolates
        # the Python-level "only Platform Admin assigns tenant_admin role"
        # check from ACL-level access entirely.
        TenantMembership = self.env["codestra.tenant.membership"]
        target = self.env["codestra.platform.user"].with_user(self.super_admin).create(
            self._platform_user_values(primary_email="future-tenant-admin@example.invalid")
        )
        with self.assertRaises(AccessError):
            TenantMembership.with_user(self.tenant_admin_user).create({
                "platform_user_id": target.id,
                "tenant_id": self.tenant.id,
                "role": "tenant_admin",
            })
        member = TenantMembership.with_user(self.tenant_admin_user).create({
            "platform_user_id": target.id,
            "tenant_id": self.tenant.id,
            "role": "member",
        })
        self.assertTrue(member)
        with self.assertRaises(AccessError):
            member.with_user(self.tenant_admin_user).write({"role": "tenant_admin"})
        member.with_user(self.platform_admin).write({"role": "tenant_admin"})
        self.assertEqual(member.role, "tenant_admin")
