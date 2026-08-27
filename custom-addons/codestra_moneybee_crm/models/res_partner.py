from odoo import api, fields, models
from odoo.exceptions import ValidationError


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


class ResPartner(models.Model):
    _inherit = "res.partner"

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

    @api.model
    def moneybee_upsert_contact(self, payload):
        """Idempotently apply the Middleware `crm.contact.upsert.v1` command.

        This method accepts business/profile attributes only. Identity secrets,
        verification codes and browser/service tokens are rejected even if a
        caller attempts to include them.
        """

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
        values = {
            "name": display_name or email,
            "email": email,
            "moneybee_user_id": user_id,
            "moneybee_organization_id": organization_id,
            "moneybee_email_verified": True,
            "moneybee_membership_type": membership_type,
        }
        if partners:
            partners.write(values)
            return {"partner_id": partners.id, "created": False}

        partner = self.create(values)
        return {"partner_id": partner.id, "created": True}
