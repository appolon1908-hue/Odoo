from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError

from .constants import (
    BEYVRA_DOMAIN,
    CANONICAL_TRACKING_HOST,
    CURRENT_SIGNED_INBOUND_DOMAINS,
    EXCLUDED_DOMAINS,
    LIVE_DELIVERY_PARAMETER,
    MANAGED_DOMAINS,
)


class MailBrand(models.Model):
    _inherit = "codestra.mail.brand"

    outbound_server_id = fields.Many2one(
        "ir.mail_server",
        string="Governed Outgoing Server",
        ondelete="restrict",
        domain=[("codestra_managed", "=", True)],
    )
    klyrow_inbound_target = fields.Selection(
        [
            ("signed_adapter", "Signed Klyrow → Middleware → Odoo"),
            ("disabled", "Disabled"),
        ],
        string="Inbound Target",
        default="disabled",
        required=True,
    )
    klyrow_inbound_observed = fields.Selection(
        [
            ("signed_adapter", "Signed adapter"),
            ("gmail_forward", "Gmail forwarding"),
            ("disabled", "Disabled"),
            ("unknown", "Unknown"),
        ],
        string="Observed Inbound Route",
        default="unknown",
        required=True,
    )
    klyrow_inbound_state = fields.Selection(
        [
            ("aligned", "Aligned"),
            ("drift", "Drift"),
            ("blocked", "Blocked"),
        ],
        string="Inbound Reconciliation",
        compute="_compute_klyrow_inbound_state",
    )
    klyrow_tracking_policy = fields.Selection(
        [
            ("canonical_only", "track.klyrow.com only"),
            ("disabled", "Disabled"),
        ],
        string="Tracking Policy",
        default="disabled",
        required=True,
    )
    klyrow_tracking_host = fields.Char(string="Tracking Host")

    @api.depends(
        "active",
        "klyrow_inbound_target",
        "klyrow_inbound_observed",
    )
    def _compute_klyrow_inbound_state(self):
        for brand in self:
            if not brand.active or brand.klyrow_inbound_target == "disabled":
                brand.klyrow_inbound_state = "blocked"
            elif brand.klyrow_inbound_target == brand.klyrow_inbound_observed:
                brand.klyrow_inbound_state = "aligned"
            else:
                brand.klyrow_inbound_state = "drift"

    @api.constrains(
        "domain",
        "active",
        "outbound_server_id",
        "klyrow_tracking_policy",
        "klyrow_tracking_host",
    )
    def _check_klyrow_brand_policy(self):
        for brand in self:
            if brand.active and brand.domain in EXCLUDED_DOMAINS:
                raise ValidationError(
                    _("booked4seasons.com cannot be activated in Klyrow/Odoo.")
                )
            if brand.domain in MANAGED_DOMAINS and brand.active:
                if (
                    not brand.outbound_server_id
                    or not brand.outbound_server_id.codestra_managed
                ):
                    raise ValidationError(
                        _("Every managed domain requires a governed outgoing server.")
                    )
                if not brand.outbound_server_id._match_from_filter(
                    f"support@{brand.domain}",
                    brand.outbound_server_id.from_filter,
                ):
                    raise ValidationError(
                        _("The outgoing server FROM filter does not cover this brand.")
                    )
                if brand.klyrow_tracking_policy != "canonical_only":
                    raise ValidationError(
                        _("Managed brands must use the canonical tracking policy.")
                    )
                if brand.klyrow_tracking_host != CANONICAL_TRACKING_HOST:
                    raise ValidationError(
                        _("Managed brands must use track.klyrow.com.")
                    )

    def write(self, values):
        governed = {
            "outbound_server_id",
            "klyrow_inbound_target",
            "klyrow_inbound_observed",
            "klyrow_tracking_policy",
            "klyrow_tracking_host",
        }.intersection(values)
        if (
            governed
            and not self.env.context.get("codestra_klyrow_routing_bootstrap")
            and not self.env.user.has_group("base.group_system")
        ):
            raise AccessError(
                _("Only a system administrator may change governed email routing.")
            )
        return super().write(values)

    @api.model
    def _provision_klyrow_routing(self):
        if not self.env.su and not self.env.user.has_group("base.group_system"):
            raise AccessError(
                _("System-administrator authority is required to provision routing.")
            )
        shared_server = self.env.ref(
            "codestra_klyrow_smtp.mail_server_klyrow_production"
        )
        beyvra_server = self.env.ref(
            "codestra_klyrow_smtp.mail_server_beyvra_production"
        )
        brands = self.sudo().with_context(active_test=False)
        for domain in sorted(MANAGED_DOMAINS):
            brand = brands.search([("domain", "=", domain)], limit=2)
            if len(brand) != 1:
                raise ValidationError(
                    _(
                        "Managed domain %(domain)s must resolve to exactly one Odoo brand.",
                        domain=domain,
                    )
                )
            observed = brand.klyrow_inbound_observed
            if observed == "unknown":
                observed = (
                    "signed_adapter"
                    if domain in CURRENT_SIGNED_INBOUND_DOMAINS
                    else "gmail_forward"
                )
            brand.with_context(codestra_klyrow_routing_bootstrap=True).write(
                {
                    "active": True,
                    "outbound_server_id": (
                        beyvra_server.id if domain == BEYVRA_DOMAIN else shared_server.id
                    ),
                    "klyrow_inbound_target": "signed_adapter",
                    "klyrow_inbound_observed": observed,
                    "klyrow_tracking_policy": "canonical_only",
                    "klyrow_tracking_host": CANONICAL_TRACKING_HOST,
                }
            )

        legacy_admin_teams = (
            self.env["codestra.mail.team"]
            .sudo()
            .with_context(active_test=False)
            .search(
                [
                    ("brand_id.domain", "in", sorted(MANAGED_DOMAINS | EXCLUDED_DOMAINS)),
                    ("queue_type_id.code", "=", "ADMINISTRATION"),
                ]
            )
        )
        if legacy_admin_teams:
            legacy_admin_teams.write({"active": False})
            (
                self.env["codestra.mail.sender.allowlist"]
                .sudo()
                .with_context(active_test=False)
                .search([("team_id", "in", legacy_admin_teams.ids)])
                .write({"active": False})
            )

        excluded = brands.search([("domain", "in", sorted(EXCLUDED_DOMAINS))])
        if excluded:
            excluded.with_context(codestra_klyrow_routing_bootstrap=True).write(
                {
                    "active": False,
                    "outbound_server_id": False,
                    "klyrow_inbound_target": "disabled",
                    "klyrow_inbound_observed": "disabled",
                    "klyrow_tracking_policy": "disabled",
                    "klyrow_tracking_host": False,
                }
            )
            teams = (
                self.env["codestra.mail.team"]
                .sudo()
                .with_context(active_test=False)
                .search([("brand_id", "in", excluded.ids)])
            )
            teams.write({"active": False})
            (
                self.env["codestra.mail.sender.allowlist"]
                .sudo()
                .with_context(active_test=False)
                .search([("team_id", "in", teams.ids)])
                .write({"active": False})
            )

        parameters = self.env["ir.config_parameter"].sudo()
        if not parameters.search_count([("key", "=", LIVE_DELIVERY_PARAMETER)]):
            parameters.set_param(LIVE_DELIVERY_PARAMETER, "false")
        return True
