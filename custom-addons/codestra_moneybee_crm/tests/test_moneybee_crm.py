from copy import deepcopy

from psycopg2 import IntegrityError

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMoneyBeeCrm(TransactionCase):
    TENANT_A = "moneybee-tenant-1001"
    TENANT_B = "moneybee-tenant-2001"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        companies = cls.env["res.company"]
        cls.company_a = companies.create(
            {
                "name": "Synthetic MoneyBee Company A",
                "moneybee_organization_id": cls.TENANT_A,
            }
        )
        cls.company_b = companies.create(
            {
                "name": "Synthetic MoneyBee Company B",
                "moneybee_organization_id": cls.TENANT_B,
            }
        )
        cls.unbound_company = companies.create(
            {"name": "Synthetic MoneyBee Unbound Company"}
        )

        users = cls.env["res.users"].with_context(no_reset_password=True)
        internal_group = cls.env.ref("base.group_user")
        middleware_group = cls.env.ref(
            "codestra_moneybee_crm.group_moneybee_middleware"
        )

        def create_user(name, login, company, allowed_companies=None, middleware=True):
            groups = [Command.link(internal_group.id)]
            if middleware:
                groups.append(Command.link(middleware_group.id))
            allowed = allowed_companies or company
            return users.create(
                {
                    "name": name,
                    "login": login,
                    "company_id": company.id,
                    "company_ids": [Command.set(allowed.ids)],
                    "group_ids": groups,
                }
            )

        cls.middleware_user_a = create_user(
            "Synthetic MoneyBee Middleware A",
            "synthetic-moneybee-middleware-a",
            cls.company_a,
        )
        cls.middleware_user_b = create_user(
            "Synthetic MoneyBee Middleware B",
            "synthetic-moneybee-middleware-b",
            cls.company_b,
        )
        cls.multi_company_middleware_user = create_user(
            "Synthetic MoneyBee Multi-company Middleware",
            "synthetic-moneybee-middleware-multi",
            cls.company_a,
            cls.company_a | cls.company_b,
        )
        cls.unbound_middleware_user = create_user(
            "Synthetic MoneyBee Unbound Middleware",
            "synthetic-moneybee-middleware-unbound",
            cls.unbound_company,
        )
        cls.ordinary_user = create_user(
            "Synthetic Ordinary User",
            "synthetic-moneybee-ordinary",
            cls.company_a,
            middleware=False,
        )

        cls.partner_model_a = (
            cls.env["res.partner"]
            .with_user(cls.middleware_user_a)
            .with_company(cls.company_a)
        )
        cls.partner_model_b = (
            cls.env["res.partner"]
            .with_user(cls.middleware_user_b)
            .with_company(cls.company_b)
        )

    def _payload(self, tenant_id=None, user_id="moneybee-user-1001", **updates):
        payload = {
            "user_id": user_id,
            "organization_id": tenant_id or self.TENANT_A,
            "email": "synthetic.moneybee@example.invalid",
            "email_verified": True,
            "membership_type": "BORROWER",
            "display_name": "Synthetic MoneyBee Borrower",
        }
        payload.update(updates)
        return payload

    def _command(
        self,
        tenant_id=None,
        command_id="moneybee-command-1001",
        source_event_id="moneybee-event-1001",
        payload=None,
        **updates,
    ):
        tenant_id = tenant_id or self.TENANT_A
        command = {
            "command_id": command_id,
            "source_event_id": source_event_id,
            "tenant_id": tenant_id,
            "command_type": "crm.contact.upsert.v1",
            "schema_version": 1,
            "payload": payload if payload is not None else self._payload(tenant_id=tenant_id),
        }
        command.update(updates)
        return command

    def test_dedicated_middleware_principal_is_required(self):
        ordinary_model = (
            self.env["res.partner"]
            .with_user(self.ordinary_user)
            .with_company(self.company_a)
        )
        with self.assertRaises(AccessError):
            ordinary_model.moneybee_apply_contact_command(self._command())

    def test_principal_must_have_one_server_bound_company(self):
        multi_model = (
            self.env["res.partner"]
            .with_user(self.multi_company_middleware_user)
            .with_company(self.company_a)
        )
        with self.assertRaises(AccessError):
            multi_model.moneybee_apply_contact_command(self._command())

        unbound_model = (
            self.env["res.partner"]
            .with_user(self.unbound_middleware_user)
            .with_company(self.unbound_company)
        )
        with self.assertRaises(AccessError):
            unbound_model.moneybee_apply_contact_command(
                self._command(tenant_id="unconfigured-tenant")
            )

    def test_command_application_and_exact_replay_are_idempotent(self):
        command = self._command()
        first = self.partner_model_a.moneybee_apply_contact_command(command)
        replay = self.partner_model_a.moneybee_apply_contact_command(command)

        self.assertEqual(first["status"], "APPLIED")
        self.assertTrue(first["created"])
        self.assertFalse(first["replayed"])
        self.assertEqual(replay["partner_id"], first["partner_id"])
        self.assertFalse(replay["created"])
        self.assertTrue(replay["replayed"])

        partner = self.env["res.partner"].browse(first["partner_id"])
        self.assertEqual(partner.company_id, self.company_a)
        self.assertEqual(partner.moneybee_organization_id, self.TENANT_A)
        self.assertEqual(
            self.env["res.partner"].search_count(
                [("moneybee_user_id", "=", command["payload"]["user_id"])]
            ),
            1,
        )
        receipt = self.env["codestra.moneybee.integration.receipt"].search(
            [("command_id", "=", command["command_id"])]
        )
        self.assertEqual(len(receipt), 1)
        self.assertEqual(receipt.company_id, self.company_a)
        self.assertEqual(receipt.principal_user_id, self.middleware_user_a)

    def test_changed_content_reusing_command_id_fails_closed(self):
        command = self._command()
        self.partner_model_a.moneybee_apply_contact_command(command)
        changed = deepcopy(command)
        changed["payload"]["email"] = "changed.moneybee@example.invalid"

        with self.assertRaises(ValidationError):
            self.partner_model_a.moneybee_apply_contact_command(changed)

    def test_nested_identity_secret_is_rejected(self):
        command = self._command(
            payload=self._payload(profile={"reset_token": "forbidden"})
        )
        with self.assertRaises(ValidationError):
            self.partner_model_a.moneybee_apply_contact_command(command)

    def test_command_and_payload_tenant_must_match_principal_scope(self):
        with self.assertRaises(ValidationError):
            self.partner_model_a.moneybee_apply_contact_command(
                self._command(tenant_id=self.TENANT_B)
            )

        mismatched_payload = self._payload(tenant_id=self.TENANT_B)
        with self.assertRaises(ValidationError):
            self.partner_model_a.moneybee_apply_contact_command(
                self._command(payload=mismatched_payload)
            )

    def test_identity_cannot_cross_tenants(self):
        command_a = self._command(
            payload=self._payload(user_id="shared-moneybee-user")
        )
        self.partner_model_a.moneybee_apply_contact_command(command_a)

        command_b = self._command(
            tenant_id=self.TENANT_B,
            command_id="moneybee-command-tenant-b",
            source_event_id="moneybee-event-tenant-b",
            payload=self._payload(
                tenant_id=self.TENANT_B,
                user_id="shared-moneybee-user",
                email="tenant-b@example.invalid",
            ),
        )
        with self.assertRaises(ValidationError):
            self.partner_model_b.moneybee_apply_contact_command(command_b)

    def test_receipts_are_visible_only_to_the_creating_principal(self):
        command = self._command()
        self.partner_model_a.moneybee_apply_contact_command(command)

        receipts_a = (
            self.env["codestra.moneybee.integration.receipt"]
            .with_user(self.middleware_user_a)
            .with_company(self.company_a)
        )
        receipts_b = (
            self.env["codestra.moneybee.integration.receipt"]
            .with_user(self.middleware_user_b)
            .with_company(self.company_b)
        )
        self.assertEqual(
            receipts_a.search_count([("command_id", "=", command["command_id"])]),
            1,
        )
        self.assertEqual(
            receipts_b.search_count([("command_id", "=", command["command_id"])]),
            0,
        )

    def test_receipts_cannot_be_forged_changed_or_deleted(self):
        command = self._command()
        result = self.partner_model_a.moneybee_apply_contact_command(command)
        receipts = (
            self.env["codestra.moneybee.integration.receipt"]
            .with_user(self.middleware_user_a)
            .with_company(self.company_a)
        )
        receipt = receipts.search([("command_id", "=", command["command_id"])])

        forged_values = {
            "command_id": "forged-command",
            "source_event_id": "forged-event",
            "tenant_id": self.TENANT_A,
            "company_id": self.company_a.id,
            "principal_user_id": self.middleware_user_a.id,
            "schema_version": 1,
            "command_type": "crm.contact.upsert.v1",
            "payload_hash": "0" * 64,
            "status": "APPLIED",
            "partner_id": result["partner_id"],
        }
        with self.assertRaises(AccessError):
            receipts.create(forged_values)
        with self.assertRaises(AccessError):
            receipt.write({"status": "FAILED"})
        with self.assertRaises(AccessError):
            receipt.unlink()

    def test_service_principal_cannot_bypass_receipted_contact_path(self):
        self.assertFalse(hasattr(self.partner_model_a, "moneybee_upsert_contact"))
        with self.assertRaises(AccessError):
            self.partner_model_a.create({"name": "Unreceipted contact"})

        result = self.partner_model_a.moneybee_apply_contact_command(self._command())
        partner = (
            self.env["res.partner"]
            .browse(result["partner_id"])
            .with_user(self.middleware_user_a)
            .with_company(self.company_a)
        )
        with self.assertRaises(AccessError):
            partner.write({"name": "Unreceipted change"})
        with self.assertRaises(AccessError):
            partner.unlink()

    def test_authoritative_mapping_fields_reject_human_edits(self):
        result = self.partner_model_a.moneybee_apply_contact_command(self._command())
        partner = (
            self.env["res.partner"]
            .browse(result["partner_id"])
            .with_user(self.ordinary_user)
            .with_company(self.company_a)
        )
        with self.assertRaises(AccessError):
            partner.write({"email": "human-change@example.invalid"})
        with self.assertRaises(AccessError):
            partner.write({"moneybee_user_id": "rebound-user"})

    def test_missing_display_name_preserves_existing_name(self):
        first = self.partner_model_a.moneybee_apply_contact_command(self._command())
        second_payload = self._payload()
        second_payload.pop("display_name")
        second = self.partner_model_a.moneybee_apply_contact_command(
            self._command(
                command_id="moneybee-command-1002",
                source_event_id="moneybee-event-1002",
                payload=second_payload,
            )
        )

        self.assertEqual(first["partner_id"], second["partner_id"])
        partner = self.env["res.partner"].browse(first["partner_id"])
        self.assertEqual(partner.name, "Synthetic MoneyBee Borrower")

    def test_company_tenant_binding_is_unique_in_database(self):
        with self.assertRaisesRegex(
            (IntegrityError, ValidationError),
            "moneybee_organization_id|MoneyBee organization",
        ), self.env.cr.savepoint():
            duplicate = self.env["res.company"].create({
                "name": "Duplicate Synthetic MoneyBee Binding",
                "moneybee_organization_id": self.TENANT_A,
            })
            duplicate.flush_recordset()

    def test_archived_identity_is_reused_without_reactivation(self):
        applied = self.partner_model_a.moneybee_apply_contact_command(self._command())
        partner = self.env["res.partner"].browse(applied["partner_id"])
        partner.active = False
        result = self.partner_model_a.moneybee_apply_contact_command(self._command(
            command_id="archived-update", source_event_id="archived-event",
        ))
        self.assertEqual(result["partner_id"], partner.id)
        self.assertFalse(result["created"])
        self.assertFalse(partner.active)
        with self.assertRaisesRegex(ValidationError, "outside the authenticated tenant scope"):
            self.partner_model_b.moneybee_apply_contact_command(self._command(
                tenant_id=self.TENANT_B, command_id="archived-cross-tenant",
                source_event_id="archived-cross-event",
            ))
