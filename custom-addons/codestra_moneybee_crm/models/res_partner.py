import hashlib
import json

from psycopg2 import IntegrityError

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .integration_receipt import MONEYBEE_RECEIPT_CREATE_TOKEN


MONEYBEE_SERVICE_GROUP = "codestra_moneybee_crm.group_moneybee_middleware"
MONEYBEE_PARTNER_WRITE_TOKEN = object()
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
MONEYBEE_MANAGED_FIELDS = MONEYBEE_FIELDS | frozenset({"company_id", "email"})


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


class ResCompany(models.Model):
    _inherit = "res.company"

    _moneybee_organization_id_uniq = models.Constraint(
        "unique(moneybee_organization_id)",
        "A MoneyBee organization can be bound to only one Odoo company.",
    )

    moneybee_organization_id = fields.Char(
        string="MoneyBee Organization ID",
        index=True,
        copy=False,
        help=(
            "Server-managed MoneyBee tenant identifier used to bind a dedicated "
            "Middleware service principal to exactly one Odoo company."
        ),
    )


class ResPartner(models.Model):
    _inherit = "res.partner"

    _moneybee_user_id_uniq = models.Constraint(
        "unique(moneybee_user_id)",
        "A MoneyBee user can be mapped to only one Odoo contact.",
    )

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

    def _is_moneybee_internal_partner_write(self):
        return (
            self.env.context.get("_moneybee_partner_write_token")
            is MONEYBEE_PARTNER_WRITE_TOKEN
        )

    def _is_moneybee_middleware_principal(self):
        group = self.env.ref(MONEYBEE_SERVICE_GROUP, raise_if_not_found=False)
        return bool(group and group in self.env.user.group_ids)

    def _assert_moneybee_middleware_principal(self):
        if not self._is_moneybee_middleware_principal():
            raise AccessError(
                "MoneyBee synchronization requires the dedicated Middleware "
                "integration principal."
            )

    def _moneybee_principal_scope(self):
        """Derive tenant scope from the authenticated service identity.

        A MoneyBee principal is deliberately bound to one and only one allowed
        Odoo company. The company's server-managed MoneyBee organization ID is
        authoritative; command and payload tenant strings are never trusted as
        the source of scope.
        """

        self._assert_moneybee_middleware_principal()
        companies = self.env.user.company_ids
        if len(companies) != 1:
            raise AccessError(
                "The MoneyBee Middleware principal must be bound to exactly one "
                "allowed Odoo company."
            )
        company = companies
        if self.env.company != company:
            raise AccessError(
                "The active Odoo company does not match the MoneyBee principal binding."
            )
        tenant_id = str(company.moneybee_organization_id or "").strip()
        if not tenant_id:
            raise AccessError(
                "The bound Odoo company has no MoneyBee organization identifier."
            )
        return company, tenant_id

    @api.model_create_multi
    def create(self, vals_list):
        internal_write = self._is_moneybee_internal_partner_write()
        is_moneybee_principal = self._is_moneybee_middleware_principal()
        if is_moneybee_principal and not internal_write:
            raise AccessError(
                "MoneyBee service principals may create contacts only through "
                "moneybee_apply_contact_command()."
            )
        if any(MONEYBEE_FIELDS.intersection(vals) for vals in vals_list):
            if not (is_moneybee_principal and internal_write):
                raise AccessError(
                    "MoneyBee identity fields are writable only by the internal "
                    "receipted command path."
                )
        return super().create(vals_list)

    def write(self, vals):
        internal_write = self._is_moneybee_internal_partner_write()
        is_moneybee_principal = self._is_moneybee_middleware_principal()
        if is_moneybee_principal and not internal_write:
            raise AccessError(
                "MoneyBee service principals may update contacts only through "
                "moneybee_apply_contact_command()."
            )
        if MONEYBEE_FIELDS.intersection(vals) and not (
            is_moneybee_principal and internal_write
        ):
            raise AccessError(
                "MoneyBee identity fields are writable only by the internal "
                "receipted command path."
            )
        if (
            MONEYBEE_MANAGED_FIELDS.intersection(vals)
            and any(self.mapped("moneybee_user_id"))
            and not internal_write
        ):
            raise AccessError(
                "MoneyBee-managed identity, tenant, company, and verified email "
                "fields cannot be changed outside the receipted command path."
            )

        if internal_write:
            incoming_user_id = str(vals.get("moneybee_user_id") or "").strip()
            incoming_organization_id = str(
                vals.get("moneybee_organization_id") or ""
            ).strip()
            incoming_company_id = vals.get("company_id")
            for partner in self:
                if (
                    incoming_user_id
                    and partner.moneybee_user_id
                    and partner.moneybee_user_id != incoming_user_id
                ):
                    raise ValidationError(
                        "An existing MoneyBee identity mapping cannot be rebound."
                    )
                if (
                    incoming_organization_id
                    and partner.moneybee_organization_id
                    and partner.moneybee_organization_id
                    != incoming_organization_id
                ):
                    raise ValidationError(
                        "An existing MoneyBee organization mapping cannot be rebound."
                    )
                if (
                    incoming_company_id
                    and partner.company_id
                    and partner.company_id.id != incoming_company_id
                ):
                    raise ValidationError(
                        "An existing MoneyBee contact cannot be moved to another "
                        "Odoo company."
                    )
        return super().write(vals)

    def unlink(self):
        if any(self.mapped("moneybee_user_id")):
            raise AccessError(
                "MoneyBee identity mappings are immutable; archive the CRM contact "
                "instead of deleting it."
            )
        if self._is_moneybee_middleware_principal():
            raise AccessError(
                "MoneyBee service principals cannot delete Odoo contacts."
            )
        return super().unlink()

    @api.model
    def _moneybee_upsert_contact(self, payload, company, tenant_id):
        """Idempotently apply a validated tenant-bound CRM contact payload."""

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
            raise ValidationError(
                "MoneyBee user_id, organization_id and email are required."
            )
        if organization_id != tenant_id:
            raise ValidationError(
                "MoneyBee contact organization does not match the authenticated "
                "principal scope."
            )
        if company != self.env.company:
            raise AccessError(
                "MoneyBee contact application requires the authenticated principal's "
                "bound Odoo company."
            )
        if membership_type not in {"BORROWER", "LENDER"}:
            raise ValidationError("Unsupported MoneyBee membership type.")
        if not email_verified:
            raise ValidationError(
                "MoneyBee CRM sync requires a verified login email."
            )

        partners = self.with_context(active_test=False).search([("moneybee_user_id", "=", user_id)], limit=2)
        if len(partners) > 1:
            raise ValidationError(
                "Duplicate MoneyBee identity mapping requires reconciliation."
            )

        display_name = str(payload.get("display_name") or "").strip()
        update_values = {
            "email": email,
            "company_id": company.id,
            "moneybee_user_id": user_id,
            "moneybee_organization_id": tenant_id,
            "moneybee_email_verified": True,
            "moneybee_membership_type": membership_type,
        }
        if display_name:
            update_values["name"] = display_name

        write_context = {
            "_moneybee_partner_write_token": MONEYBEE_PARTNER_WRITE_TOKEN
        }
        if partners:
            partner = partners
            if (
                partner.moneybee_organization_id != tenant_id
                or partner.company_id != company
            ):
                raise ValidationError(
                    "The MoneyBee user is already mapped outside the authenticated "
                    "tenant scope."
                )
            partner.with_context(**write_context).write(update_values)
            return {"partner_id": partner.id, "created": False}

        create_values = dict(update_values)
        create_values["name"] = display_name or email
        try:
            with self.env.cr.savepoint():
                partner = self.with_context(**write_context).create(create_values)
        except IntegrityError:
            partner = self.with_context(active_test=False).search([("moneybee_user_id", "=", user_id)], limit=1)
            if not partner:
                raise
            if (
                partner.moneybee_organization_id != tenant_id
                or partner.company_id != company
            ):
                raise ValidationError(
                    "A concurrent MoneyBee identity collision crossed tenant scope."
                )
            partner.with_context(**write_context).write(update_values)
            return {"partner_id": partner.id, "created": False}

        return {"partner_id": partner.id, "created": True}

    @api.model
    def moneybee_apply_contact_command(self, command):
        """Apply one authenticated Middleware command with an immutable receipt.

        Exact replays return the original result. A command ID reused with
        different content fails closed. Tenant scope is derived from the
        authenticated service principal and its one allowed Odoo company.
        """

        company, principal_tenant_id = self._moneybee_principal_scope()
        if not isinstance(command, dict):
            raise ValidationError("MoneyBee Middleware command must be an object.")
        _assert_no_identity_secrets(command, "command")

        command_id = str(command.get("command_id") or "").strip()
        source_event_id = str(command.get("source_event_id") or "").strip()
        command_tenant_id = str(command.get("tenant_id") or "").strip()
        command_type = str(command.get("command_type") or "").strip()
        schema_version = command.get("schema_version")
        payload = command.get("payload")
        if not all((command_id, source_event_id, command_tenant_id)):
            raise ValidationError(
                "command_id, source_event_id and tenant_id are required."
            )
        if command_type != "crm.contact.upsert.v1":
            raise ValidationError("Unsupported MoneyBee CRM command type.")
        if schema_version != 1:
            raise ValidationError(
                "Unsupported MoneyBee CRM command schema version."
            )
        if not isinstance(payload, dict):
            raise ValidationError("MoneyBee CRM command payload must be an object.")
        payload_tenant_id = str(payload.get("organization_id") or "").strip()
        if (
            command_tenant_id != principal_tenant_id
            or payload_tenant_id != principal_tenant_id
        ):
            raise ValidationError(
                "MoneyBee command tenant does not match the authenticated "
                "principal scope."
            )

        digest = _payload_hash(payload)
        receipts = self.env["codestra.moneybee.integration.receipt"]
        receipt_domain = [
            ("principal_user_id", "=", self.env.user.id),
            ("company_id", "=", company.id),
            ("tenant_id", "=", principal_tenant_id),
            ("command_id", "=", command_id),
        ]
        existing = receipts.search(receipt_domain, limit=1)
        if existing:
            if (
                existing.payload_hash != digest
                or existing.source_event_id != source_event_id
                or existing.command_type != command_type
                or existing.schema_version != schema_version
            ):
                raise ValidationError(
                    "MoneyBee command ID was already used with different command "
                    "content."
                )
            return {
                "status": existing.status,
                "partner_id": existing.partner_id.id or None,
                "created": False,
                "replayed": True,
                "command_id": command_id,
            }

        result = self._moneybee_upsert_contact(
            payload,
            company=company,
            tenant_id=principal_tenant_id,
        )
        partner_id = result.get("partner_id")
        receipt_values = {
            "command_id": command_id,
            "source_event_id": source_event_id,
            "tenant_id": principal_tenant_id,
            "company_id": company.id,
            "principal_user_id": self.env.user.id,
            "schema_version": schema_version,
            "command_type": command_type,
            "payload_hash": digest,
            "status": "APPLIED",
            "applied_at": fields.Datetime.now(),
            "partner_id": partner_id,
        }
        try:
            with self.env.cr.savepoint():
                receipts.with_context(
                    _moneybee_receipt_create_token=MONEYBEE_RECEIPT_CREATE_TOKEN
                ).create(receipt_values)
        except IntegrityError:
            existing = receipts.search(receipt_domain, limit=1)
            if (
                not existing
                or existing.payload_hash != digest
                or existing.source_event_id != source_event_id
                or existing.command_type != command_type
                or existing.schema_version != schema_version
            ):
                raise ValidationError(
                    "Concurrent MoneyBee command receipt conflict requires "
                    "reconciliation."
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
