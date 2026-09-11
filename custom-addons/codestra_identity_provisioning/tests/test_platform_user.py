from psycopg2.errors import UniqueViolation

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
