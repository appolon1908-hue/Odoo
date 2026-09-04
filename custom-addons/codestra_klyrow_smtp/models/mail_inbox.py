from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError

from .constants import CANONICAL_TRACKING_HOST, EXCLUDED_DOMAINS, MANAGED_DOMAINS


class MailTeam(models.Model):
    _inherit = "codestra.mail.team"

    codestra_delivery_ready = fields.Boolean(
        string="Klyrow Delivery Ready",
        related="brand_id.outbound_server_id.codestra_delivery_ready",
        readonly=True,
    )
    codestra_inbound_state = fields.Selection(
        related="brand_id.klyrow_inbound_state",
        string="Inbound Reconciliation",
        readonly=True,
    )

    @api.constrains("active", "brand_id", "queue_type_id")
    def _check_governed_brand_team(self):
        for team in self:
            if team.active and team.brand_id.domain in EXCLUDED_DOMAINS:
                raise ValidationError(
                    _("Excluded domains cannot have active Odoo inbox teams.")
                )
            if (
                team.active
                and team.brand_id.domain in MANAGED_DOMAINS
                and team.queue_type_id.code not in {"SUPPORT", "BILLING"}
            ):
                raise ValidationError(
                    _("Managed domains may expose only support and billing inbox teams.")
                )


class MailSenderAllowlist(models.Model):
    _inherit = "codestra.mail.sender.allowlist"

    @api.constrains("active", "team_id")
    def _check_governed_brand_sender(self):
        for sender_rule in self:
            team = sender_rule.team_id
            if sender_rule.active and team.brand_id.domain in EXCLUDED_DOMAINS:
                raise ValidationError(
                    _("Excluded domains cannot have active sender rules.")
                )
            if (
                sender_rule.active
                and team.brand_id.domain in MANAGED_DOMAINS
                and team.queue_type_id.code not in {"SUPPORT", "BILLING"}
            ):
                raise ValidationError(
                    _("Managed domains may expose only support and billing senders.")
                )


class MailConversation(models.Model):
    _inherit = "codestra.mail.conversation"

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        custom_values = dict(custom_values or {})
        team = (
            self.env["codestra.mail.team"]
            .with_context(active_test=False)
            .browse(custom_values.get("team_id"))
            .exists()
        )
        if team and (
            not team.active
            or not team.brand_id.active
            or team.brand_id.domain in EXCLUDED_DOMAINS
        ):
            raise ValidationError(_("The inbound destination is disabled."))
        if (
            team
            and team.brand_id.domain in MANAGED_DOMAINS
            and not self.env.context.get("codestra_signed_inbound_adapter")
        ):
            raise AccessError(
                _(
                    "Managed inbound email must arrive through the signed "
                    "Klyrow → Middleware → Odoo adapter."
                )
            )
        return super().message_new(msg_dict, custom_values=custom_values)

    def prepare_outbound(self, idempotency_key, supplied_from=None):
        values = super().prepare_outbound(
            idempotency_key,
            supplied_from=supplied_from,
        )
        self.ensure_one()
        server = self.brand_id.outbound_server_id
        if not server or not server._match_from_filter(
            values["sender"], server.from_filter
        ):
            raise ValidationError(
                _("No exact governed SMTP route exists for this sender.")
            )
        server.invalidate_recordset(
            [
                "codestra_secret_loaded",
                "codestra_delivery_ready",
                "codestra_readiness_message",
            ]
        )
        values.update(
            {
                "mail_server_id": server.id,
                "provider": "klyrow",
                "tracking_host": CANONICAL_TRACKING_HOST,
                "external_delivery_enabled": bool(server.codestra_delivery_ready),
                "delivery_readiness": server.codestra_readiness_message,
            }
        )
        return values
