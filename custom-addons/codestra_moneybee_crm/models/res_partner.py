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
        """Idempotently apply the Middleware `crm.contact.upsert.v1` command.

        The RPC entry point is restricted to the dedicated Middleware integration
        group. Identity secrets, verification codes and browser/service tokens are
        rejected even if a caller attempts to include them.
        """

        self._assert_moneybee_middleware_principal()
        if not isinstance(payload, dict):
            raise ValidationError("MoneyBee contact payload must be an object.")
        forbidden = FORBIDDEN_IDENTITY_FIELDS.intersection(payload)
        if forbidden:
            raise ValidationError("Identity secret material is prohibited in CRM sync.")

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
            # A concurrent delivery may have inserted the same immutable
            # MoneyBee identity first. The unique DB constraint is authoritative;
            # reconcile to the winning row instead of creating a duplicate.
            partner = self.search([("moneybee_user_id", "=", user_id)], limit=1)
            if not partner:
                raise
            partner.write(update_values)
            return {"partner_id": partner.id, "created": False}

        return {"partner_id": partner.id, "created": True}
