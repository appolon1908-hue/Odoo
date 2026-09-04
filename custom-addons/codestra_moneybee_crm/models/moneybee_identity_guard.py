from psycopg2 import IntegrityError

from odoo import api, models
from odoo.exceptions import ValidationError


class ResPartnerMoneyBeeIdentityGuard(models.Model):
    """Fail closed when record rules hide a MoneyBee identity collision.

    MoneyBee integration principals are intentionally restricted to one company.
    A normal tenant-scoped search therefore cannot see an identity already bound
    to another tenant.  The collision probe uses sudo only to read the immutable
    identity/tenant binding; every create or update remains on the authenticated
    principal's normal environment in the underlying implementation.
    """

    _inherit = "res.partner"

    @api.model
    def _moneybee_assert_global_identity_scope(self, user_id, company, tenant_id):
        identities = self.sudo().search(
            [("moneybee_user_id", "=", user_id)],
            limit=2,
        )
        if len(identities) > 1:
            raise ValidationError(
                "Duplicate MoneyBee identity mapping requires reconciliation."
            )

        identity = identities[:1]
        if identity and (
            identity.moneybee_organization_id != tenant_id
            or identity.company_id.id != company.id
        ):
            raise ValidationError(
                "The MoneyBee user is already mapped outside the authenticated "
                "tenant scope."
            )
        return identity

    @api.model
    def _moneybee_upsert_contact(self, payload, company, tenant_id):
        self._assert_moneybee_middleware_principal()
        user_id = ""
        if isinstance(payload, dict):
            user_id = str(payload.get("user_id") or "").strip()

        if user_id:
            self._moneybee_assert_global_identity_scope(
                user_id,
                company=company,
                tenant_id=tenant_id,
            )

        try:
            return super()._moneybee_upsert_contact(
                payload,
                company=company,
                tenant_id=tenant_id,
            )
        except IntegrityError:
            # The underlying implementation already rolled its failed write back
            # to a savepoint. Re-probe globally so a concurrent cross-tenant race
            # is reported as a validation failure rather than leaking SQL state.
            if user_id:
                self._moneybee_assert_global_identity_scope(
                    user_id,
                    company=company,
                    tenant_id=tenant_id,
                )
            raise
