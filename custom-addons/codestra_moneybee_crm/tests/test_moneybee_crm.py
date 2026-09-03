from copy import deepcopy

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMoneyBeeCrm(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        users = cls.env["res.users"].with_context(no_reset_password=True)
        internal_group = cls.env.ref("base.group_user")
        middleware_group = cls.env.ref(
            "codestra_moneybee_crm.group_moneybee_middleware"
        )
        cls.middleware_user = users.create(
            {
                "name": "Synthetic MoneyBee Middleware",
                "login": "synthetic-moneybee-middleware",
                "group_ids": [
                    Command.link(internal_group.id),
                    Command.link(middleware_group.id),
                ],
            }
        )
        cls.ordinary_user = users.create(
            {
                "name": "Synthetic Ordinary User",
                "login": "synthetic-moneybee-ordinary",
                "group_ids": [Command.link(internal_group.id)],
            }
        )
        cls.partner_model = cls.env["res.partner"].with_user(
            cls.middleware_user
        )

    def _payload(self, **updates):
        payload = {
            "user_id": "moneybee-user-1001",
            "organization_id": "moneybee-tenant-1001",
            "email": "synthetic.moneybee@example.invalid",
            "email_verified": True,
            "membership_type": "BORROWER",
            "display_name": "Synthetic MoneyBee Borrower",
        }
        payload.update(updates)
        return payload

    def _command(self, **updates):
        command = {
            "command_id": "moneybee-command-1001",
            "source_event_id": "moneybee-event-1001",
            "tenant_id": "moneybee-tenant-1001",
            "command_type": "crm.contact.upsert.v1",
            "schema_version": 1,
            "payload": self._payload(),
        }
        command.update(updates)
        return command

    def test_dedicated_middleware_principal_is_required(self):
        with self.assertRaises(AccessError):
            self.env["res.partner"].with_user(
                self.ordinary_user
            ).moneybee_upsert_contact(self._payload())

    def test_command_application_and_exact_replay_are_idempotent(self):
        command = self._command()
        first = self.partner_model.moneybee_apply_contact_command(command)
        replay = self.partner_model.moneybee_apply_contact_command(command)

        self.assertEqual(first["status"], "APPLIED")
        self.assertTrue(first["created"])
        self.assertFalse(first["replayed"])
        self.assertEqual(replay["partner_id"], first["partner_id"])
        self.assertFalse(replay["created"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(
            self.env["res.partner"].search_count(
                [("moneybee_user_id", "=", command["payload"]["user_id"])]
            ),
            1,
        )
        self.assertEqual(
            self.env["codestra.moneybee.integration.receipt"].search_count(
                [("command_id", "=", command["command_id"])]
            ),
            1,
        )

    def test_changed_content_reusing_command_id_fails_closed(self):
        command = self._command()
        self.partner_model.moneybee_apply_contact_command(command)
        changed = deepcopy(command)
        changed["payload"]["email"] = "changed.moneybee@example.invalid"

        with self.assertRaises(ValidationError):
            self.partner_model.moneybee_apply_contact_command(changed)

    def test_nested_identity_secret_is_rejected(self):
        payload = self._payload(profile={"reset_token": "forbidden"})
        with self.assertRaises(ValidationError):
            self.partner_model.moneybee_upsert_contact(payload)

    def test_tenant_must_match_payload_organization(self):
        command = self._command(tenant_id="another-tenant")
        with self.assertRaises(ValidationError):
            self.partner_model.moneybee_apply_contact_command(command)

    def test_existing_moneybee_identity_cannot_be_rebound(self):
        result = self.partner_model.moneybee_upsert_contact(self._payload())
        partner = self.env["res.partner"].browse(result["partner_id"]).with_user(
            self.middleware_user
        )
        with self.assertRaises(ValidationError):
            partner.write({"moneybee_user_id": "moneybee-user-rebound"})
