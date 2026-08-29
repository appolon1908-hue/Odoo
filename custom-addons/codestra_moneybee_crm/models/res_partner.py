import hashlib
import json

from psycopg2 import IntegrityError

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


FORBIDDEN_IDENTITY_FIELDS = frozenset(
    {
        "password",
        "password_hash",
        "verification_code",
        "otp",
        "otp_hash",
        "reset_token",
        "reset_url",
        "access_token",
        "refresh_token",
        "smtp_password",
        "keycloak_admin_credential",
    }
)
MONEYBEE_FIELDS = frozenset(
    {
        "moneybee_user_id",
        "moneybee_organization_id",
        "moneybee_email_verified",
        "moneybee_membership_type",
    }
)


def _assert_no_identity_secrets(value, path="payload"):
    if isinstance(value, dict):
        for raw_key, nested in value.items():
            key = str(raw_key).strip().lower()
            if key in FORBIDDEN_IDENTITY_FIELDS:
                raise ValidationError(
                    f"Identity secret material is prohibited at {path}.{key}."
                )
            _assert_no_identity_secrets(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _assert_no_identity_secrets(nested, f"{path}[{index}]")


def _payload_hash(payload):
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class ResPartner(models.Model):
    _inherit = "res.partner"

    _sql_constraints = [
        (
            "moneybee_user_id_uniq",
            "unique(moneybee_user_id)",
            "A MoneyBee user can be mapped to only one Odoo contact.",
        ),
    ]

    moneybee_user_id = fields.Char(
        string="MoneyBee User ID",
        index=True,
        copy=False,
        readonly=True,
    )
    moneybee_organization_id = fields.Char(
        string="MoneyBee Organization ID",
        index=True,
        copy=False,
        readonly=True,
    )
    moneybee_email_verified = fields.Boolean(
        string="MoneyBee Email Verified",
        copy=False,
        readonly=True,
    )
    moneybee_membership_type = fields.Selection(
        [("BORROWER", "Borrower"), ("LENDER", "Lender")],
        string="MoneyBee Membership",
        copy=False,
        readonly=True,
    )

    def _assert_moneybee_middleware_principal(self):
        if not self.env.user.has_group(
            "codestra_moneybee_crm.group_moneybee_middleware"
        ):
            raise AccessError(
                "MoneyBee identity fields are writable only by the Middleware integration principal."
            )

    @api.model_create_multi
    def create(self, vals_list):
        if any(MONEYBEE_FIELDS.intersection(vals) for vals in vals_list):
            self._assert_moneybee_middleware_principal()
        return super().create(vals_list)

    def write(self, vals):
        if MONEYBEE_FIELDS.intersection(vals):
            self._assert_moneybee_middleware_principal()
            incoming_user_id = str(vals.get("moneybee_user_id") or "").strip()
            if incoming_user_id:
                for partner in self:
                    if (
                        partner.moneybee_user_id
                        and partner.moneybee_user_id != incoming_user_id
                    ):
                        raise ValidationError(
                            "An existing MoneyBee identity mapping cannot be rebound."
                        )
        return super().write(vals)

    @api.model
    def moneybee_upsert_contact(self, payload):
        """Idempotently apply the Middleware `crm.contact.upsert.v1` payload."""

        self._assert_moneybee_middleware_principal()
        if not isinstance(payload, dict):
            raise ValidationError("MoneyBee contact payload must be an object.")
        _assert_no_identity_secrets(payload)

        user_id = str(payload.get("user_id") or "").strip()
        organization_id = str(payload.get("organization_id") or "").strip()
        email = str(payload.get("email") or "").strip().lower()
        membership_type = str(payload.get("membership_type") or "").strip().upper()
        email_verified = payload.get("email_verified") is True
        if not user_id or not organization_id or not email:
            raise ValidationError("MoneyBee user_id, organization_id and email are required.")
        if membership_type not in {"BORROWER", "LENDER"}:
            raise ValidationError("Unsupported MoneyBee membership type.")
        if not email_verified:
            raise ValidationError("MoneyBee CRM sync requires a verified login email.")

        partners = self.search([("moneybee_user_id", "=", user_id)], limit=2)
        if len(partners) > 1:
            raise ValidationError("Duplicate MoneyBee identity mapping requires reconciliation.")

        display_name = str(payload.get("display_name") or "").strip()
        update_values = {
            "email": email,
            "moneybee_user_id": user_id,
            "moneybee_organization_id": organization_id,
            "moneybee_email_verified": True,
            "moneybee_membership_type": membership_type,
        }
        if display_name:
            update_values["name"] = display_name

        if partners:
            partners.write(update_values)
            return {"partner_id": partners.id, "created": False}

        create_values = dict(update_values)
        create_values["name"] = display_name or email
        try:
            with self.env.cr.savepoint():
                partner = self.create(create_values)
        except IntegrityError:
            partner = self.search([("moneybee_user_id", "=", user_id)], limit=1)
            if not partner:
                raise
            partner.write(update_values)
            return {"partner_id": partner.id, "created": False}

        return {"partner_id": partner.id, "created": True}

    @api.model
    def moneybee_apply_contact_command(self, command):
        """Apply one Middleware command with an immutable command receipt.

        This is the preferred enterprise integration entry point. Replays with the
        same command ID and payload hash return the original result; a command ID
        reused with different content fails closed.
        """

        self._assert_moneybee_middleware_principal()
        if not isinstance(command, dict):
            raise ValidationError("MoneyBee Middleware command must be an object.")
        _assert_no_identity_secrets(command, "command")

        command_id = str(command.get("command_id") or "").strip()
        source_event_id = str(command.get("source_event_id") or "").strip()
        tenant_id = str(command.get("tenant_id") or "").strip()
        command_type = str(command.get("command_type") or "").strip()
        schema_version = command.get("schema_version")
        payload = command.get("payload")
        if not all((command_id, source_event_id, tenant_id)):
            raise ValidationError(
                "command_id, source_event_id and tenant_id are required."
            )
        if command_type != "crm.contact.upsert.v1":
            raise ValidationError("Unsupported MoneyBee CRM command type.")
        if schema_version != 1:
            raise ValidationError("Unsupported MoneyBee CRM command schema version.")
        if not isinstance(payload, dict):
            raise ValidationError("MoneyBee CRM command payload must be an object.")
        if str(payload.get("organization_id") or "").strip() != tenant_id:
            raise ValidationError("MoneyBee CRM command tenant does not match payload organization.")

        digest = _payload_hash(payload)
        receipts = self.env["codestra.moneybee.integration.receipt"]
        existing = receipts.search([("command_id", "=", command_id)], limit=1)
        if existing:
            if (
                existing.payload_hash != digest
                or existing.source_event_id != source_event_id
                or existing.tenant_id != tenant_id
                or existing.command_type != command_type
            ):
                raise ValidationError(
                    "MoneyBee command ID was already used with different command content."
                )
            return {
                "status": existing.status,
                "partner_id": existing.partner_id.id or None,
                "created": False,
                "replayed": True,
                "command_id": command_id,
            }

        result = self.moneybee_upsert_contact(payload)
        partner_id = result.get("partner_id")
        try:
            with self.env.cr.savepoint():
                receipts.create(
                    {
                        "command_id": command_id,
                        "source_event_id": source_event_id,
                        "tenant_id": tenant_id,
                        "schema_version": schema_version,
                        "command_type": command_type,
                        "payload_hash": digest,
                        "status": "APPLIED",
                        "applied_at": fields.Datetime.now(),
                        "partner_id": partner_id,
                    }
                )
        except IntegrityError:
            existing = receipts.search([("command_id", "=", command_id)], limit=1)
            if not existing or existing.payload_hash != digest:
                raise ValidationError(
                    "Concurrent MoneyBee command receipt conflict requires reconciliation."
                )
            return {
                "status": existing.status,
                "partner_id": existing.partner_id.id or partner_id,
                "created": False,
                "replayed": True,
                "command_id": command_id,
            }

        return {
            "status": "APPLIED",
            "partner_id": partner_id,
            "created": bool(result.get("created")),
            "replayed": False,
            "command_id": command_id,
        }
