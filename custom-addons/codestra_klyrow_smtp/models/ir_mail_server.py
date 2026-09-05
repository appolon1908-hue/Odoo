from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from .constants import (
    BEYVRA_DOMAIN,
    CANONICAL_TRACKING_HOST,
    EXCLUDED_DOMAINS,
    LIVE_DELIVERY_ENVIRONMENT_SWITCHES,
    LIVE_DELIVERY_PARAMETER,
    MANAGED_DOMAINS,
    SHARED_KLYROW_DOMAINS,
    domain_from_address,
    switch_enabled,
    true_values,
)


TRUE_VALUES = true_values()


class IrMailServer(models.Model):
    _inherit = "ir.mail_server"

    codestra_managed = fields.Boolean(
        string="Codestra Governed",
        default=False,
        index=True,
        help="Marks servers whose routing and activation are governed by Codestra.",
    )
    codestra_profile = fields.Selection(
        [
            ("shared", "Klyrow Production"),
            ("beyvra", "Beyvra Production"),
        ],
        string="Klyrow Profile",
        index=True,
    )
    codestra_credential_name = fields.Char(
        string="Postal Credential",
        groups="base.group_system",
        readonly=True,
    )
    codestra_credential_state = fields.Selection(
        [
            ("missing", "Missing"),
            ("hold", "Held"),
            ("active", "Active"),
            ("revoked", "Revoked"),
            ("unknown", "Unknown"),
        ],
        string="Credential State",
        default="unknown",
        required=True,
        groups="base.group_system",
    )
    codestra_secret_source = fields.Char(
        string="Secret Source",
        groups="base.group_system",
        readonly=True,
    )
    codestra_secret_loaded_at = fields.Datetime(
        string="Secret Loaded At",
        groups="base.group_system",
        readonly=True,
    )
    codestra_tracking_policy = fields.Selection(
        [("canonical_only", "Canonical host only")],
        string="Tracking Policy",
    )
    codestra_tracking_host = fields.Char(string="Tracking Host")
    codestra_secret_loaded = fields.Boolean(
        string="Password Loaded",
        compute="_compute_codestra_delivery_readiness",
    )
    codestra_delivery_ready = fields.Boolean(
        string="Delivery Ready",
        compute="_compute_codestra_delivery_readiness",
    )
    codestra_readiness_message = fields.Char(
        string="Readiness",
        compute="_compute_codestra_delivery_readiness",
    )

    @api.depends(
        "active",
        "smtp_pass",
        "codestra_managed",
        "codestra_profile",
        "codestra_credential_state",
    )
    def _compute_codestra_delivery_readiness(self):
        parameter_value = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(LIVE_DELIVERY_PARAMETER, "false")
        )
        parameter_enabled = str(parameter_value).strip().lower() in TRUE_VALUES
        for server in self:
            secret_loaded = bool(server.sudo().smtp_pass)
            server.codestra_secret_loaded = secret_loaded
            if not server.codestra_managed:
                server.codestra_delivery_ready = bool(server.active)
                server.codestra_readiness_message = _("Not Codestra-governed")
                continue

            blockers = []
            if not server.active:
                blockers.append(_("server archived"))
            if not secret_loaded:
                blockers.append(_("password not loaded"))
            if server.codestra_credential_state != "active":
                blockers.append(
                    _("credential state is %s") % (server.codestra_credential_state or "unknown")
                )
            if not parameter_enabled:
                blockers.append(_("%s is disabled") % LIVE_DELIVERY_PARAMETER)
            for switch_name in LIVE_DELIVERY_ENVIRONMENT_SWITCHES:
                if not switch_enabled(switch_name):
                    blockers.append(_("%s is disabled") % switch_name)

            server.codestra_delivery_ready = not blockers
            server.codestra_readiness_message = (
                _("Ready for governed delivery")
                if not blockers
                else _("Blocked: %s") % ", ".join(blockers)
            )

    @api.constrains("codestra_managed", "codestra_profile")
    def _check_codestra_profile_unique(self):
        for server in self.filtered(
            lambda item: item.codestra_managed and item.codestra_profile
        ):
            duplicate_count = (
                self.sudo()
                .with_context(active_test=False)
                .search_count(
                    [
                        ("id", "!=", server.id),
                        ("codestra_managed", "=", True),
                        ("codestra_profile", "=", server.codestra_profile),
                    ],
                    limit=1,
                )
            )
            if duplicate_count:
                raise ValidationError(
                    _("Each governed Klyrow profile must be unique.")
                )

    @api.constrains(
        "codestra_managed",
        "codestra_profile",
        "codestra_credential_name",
        "codestra_secret_source",
        "codestra_tracking_policy",
        "codestra_tracking_host",
        "smtp_host",
        "smtp_port",
        "smtp_encryption",
        "smtp_authentication",
        "smtp_user",
        "smtp_debug",
        "from_filter",
    )
    def _check_codestra_klyrow_profile(self):
        for server in self.filtered("codestra_managed"):
            if server.smtp_host != "mail.klyrow.com":
                raise ValidationError(_("Governed Klyrow SMTP must use mail.klyrow.com."))
            if server.smtp_port != 25:
                raise ValidationError(_("Governed Klyrow SMTP must use port 25."))
            if server.smtp_encryption != "starttls_strict":
                raise ValidationError(
                    _("Governed Klyrow SMTP must use validated STARTTLS.")
                )
            if server.smtp_authentication != "login":
                raise ValidationError(
                    _("Governed Klyrow SMTP must use username/password authentication.")
                )
            if server.smtp_debug:
                raise ValidationError(
                    _("SMTP protocol debugging is prohibited for governed production servers.")
                )
            if server.codestra_secret_source != "/etc/klyrow/odoo-postal.env":
                raise ValidationError(_("The approved Klyrow secret source is required."))
            if server.codestra_tracking_policy != "canonical_only":
                raise ValidationError(_("Only the canonical tracking-host policy is allowed."))
            if server.codestra_tracking_host != CANONICAL_TRACKING_HOST:
                raise ValidationError(
                    _("All governed tracking links must use track.klyrow.com.")
                )

            filters = server._parse_from_filter(server.from_filter)
            if len(filters) != len(set(filters)):
                raise ValidationError(_("Duplicate FROM filters are not allowed."))

            if server.codestra_profile == "shared":
                if set(filters) != set(SHARED_KLYROW_DOMAINS):
                    raise ValidationError(
                        _("The Klyrow Production server must contain the exact 13-domain filter.")
                    )
                if server.smtp_user != "klyrow/klyrow-production":
                    raise ValidationError(
                        _("The Klyrow Production SMTP username is fixed.")
                    )
                if server.codestra_credential_name != "klyrow-production":
                    raise ValidationError(
                        _("The Klyrow Production credential name is fixed.")
                    )
            elif server.codestra_profile == "beyvra":
                if filters != [BEYVRA_DOMAIN]:
                    raise ValidationError(
                        _("The Beyvra server must be filtered only to beyvra.com.")
                    )
                if server.smtp_user != "klyrow/beyvra-production":
                    raise ValidationError(_("The Beyvra SMTP username is fixed."))
                if server.codestra_credential_name != "beyvra-production":
                    raise ValidationError(
                        _("The Beyvra Production credential name is fixed.")
                    )
            else:
                raise ValidationError(_("A governed Klyrow profile is required."))

            if EXCLUDED_DOMAINS.intersection(filters):
                raise ValidationError(
                    _("booked4seasons.com is excluded because it remains on Mailgun.")
                )

    def _ensure_codestra_delivery_ready(self):
        self.invalidate_recordset(
            [
                "codestra_secret_loaded",
                "codestra_delivery_ready",
                "codestra_readiness_message",
            ]
        )
        for server in self.filtered("codestra_managed"):
            if not server.codestra_delivery_ready:
                raise UserError(
                    _(
                        "Live Klyrow delivery is blocked for %(server)s. %(reason)s",
                        server=server.display_name,
                        reason=server.codestra_readiness_message,
                    )
                )
        return True

    @api.model
    def _filter_mail_servers_fallback(self, servers):
        servers = super()._filter_mail_servers_fallback(servers)
        return servers.filtered(lambda server: not server.codestra_managed)

    def _find_mail_server(self, email_from, mail_servers=None):
        sender_domain = domain_from_address(email_from)
        if sender_domain in MANAGED_DOMAINS:
            candidates = (
                self.sudo()
                .with_context(active_test=False)
                .search([("codestra_managed", "=", True)], order="sequence, id")
                .filtered(lambda server: server._match_from_filter(email_from, server.from_filter))
            )
            if len(candidates) != 1:
                raise UserError(
                    _(
                        "The FROM domain %(domain)s must resolve to exactly one governed Klyrow server.",
                        domain=sender_domain,
                    )
                )
            candidates._ensure_codestra_delivery_ready()
            return candidates, email_from
        return super()._find_mail_server(email_from, mail_servers=mail_servers)

    def _check_forced_mail_server(self, mail_server, allow_archived, smtp_from):
        result = super()._check_forced_mail_server(
            mail_server, allow_archived, smtp_from
        )
        if mail_server.codestra_managed:
            if not smtp_from or not mail_server._match_from_filter(
                smtp_from, mail_server.from_filter
            ):
                raise UserError(
                    _("A governed Klyrow server cannot be forced for another FROM domain.")
                )
        return result

    def _connect__(
        self,
        host=None,
        port=None,
        user=None,
        password=None,
        encryption=None,
        smtp_from=None,
        ssl_certificate=None,
        ssl_private_key=None,
        smtp_debug=False,
        mail_server_id=None,
        allow_archived=False,
    ):
        selected_server = self.env["ir.mail_server"]
        direct_sender_domain = domain_from_address(smtp_from)
        if host and not mail_server_id and direct_sender_domain in MANAGED_DOMAINS:
            raise UserError(
                _("Managed Klyrow FROM domains cannot use direct SMTP parameters.")
            )
        if mail_server_id:
            selected_server = (
                self.sudo().with_context(active_test=False).browse(mail_server_id).exists()
            )
        elif not host:
            selected_server, smtp_from = self.sudo()._find_mail_server(smtp_from)
            if selected_server:
                mail_server_id = selected_server.id

        connection_test = bool(
            self.env.context.get("codestra_smtp_connection_test")
        )
        if (
            selected_server
            and selected_server.codestra_managed
            and not connection_test
        ):
            selected_server._ensure_codestra_delivery_ready()

        connection = super()._connect__(
            host=host,
            port=port,
            user=user,
            password=password,
            encryption=encryption,
            smtp_from=smtp_from,
            ssl_certificate=ssl_certificate,
            ssl_private_key=ssl_private_key,
            smtp_debug=smtp_debug,
            mail_server_id=mail_server_id,
            allow_archived=allow_archived,
        )
        if connection is not None and selected_server:
            connection.codestra_mail_server_id = selected_server.id
            connection.codestra_managed = bool(selected_server.codestra_managed)
        return connection

    @api.model
    def send_email(
        self,
        message,
        mail_server_id=None,
        smtp_server=None,
        smtp_port=None,
        smtp_user=None,
        smtp_password=None,
        smtp_encryption=None,
        smtp_ssl_certificate=None,
        smtp_ssl_private_key=None,
        smtp_debug=False,
        smtp_session=None,
    ):
        sender_domain = domain_from_address(message["From"])
        if (
            sender_domain in MANAGED_DOMAINS
            and smtp_session is None
            and smtp_server is not None
            and not mail_server_id
        ):
            raise UserError(
                _("Managed Klyrow FROM domains cannot use direct SMTP parameters.")
            )
        if sender_domain in MANAGED_DOMAINS and smtp_session is not None:
            server_id = getattr(smtp_session, "codestra_mail_server_id", False)
            server = (
                self.sudo().with_context(active_test=False).browse(server_id).exists()
                if server_id
                else self.env["ir.mail_server"]
            )
            if (
                not server
                or not server.codestra_managed
                or not server._match_from_filter(message["From"], server.from_filter)
            ):
                raise UserError(
                    _("Managed Klyrow FROM domains require a governed SMTP session.")
                )
            server._ensure_codestra_delivery_ready()

        return super().send_email(
            message,
            mail_server_id=mail_server_id,
            smtp_server=smtp_server,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            smtp_encryption=smtp_encryption,
            smtp_ssl_certificate=smtp_ssl_certificate,
            smtp_ssl_private_key=smtp_ssl_private_key,
            smtp_debug=smtp_debug,
            smtp_session=smtp_session,
        )

    def test_smtp_connection(self, autodetect_max_email_size=False):
        action = super(
            IrMailServer,
            self.with_context(codestra_smtp_connection_test=True),
        ).test_smtp_connection(
            autodetect_max_email_size=autodetect_max_email_size
        )
        self.invalidate_recordset(
            [
                "codestra_secret_loaded",
                "codestra_delivery_ready",
                "codestra_readiness_message",
            ]
        )
        blocked = self.filtered(
            lambda server: server.codestra_managed
            and not server.codestra_delivery_ready
        )
        if blocked:
            reasons = "; ".join(
                f"{server.display_name}: {server.codestra_readiness_message}"
                for server in blocked
            )
            action["params"].update(
                {
                    "type": "warning",
                    "sticky": True,
                    "message": _(
                        "SMTP connectivity and authentication passed, but live delivery "
                        "remains blocked. %s"
                    )
                    % reasons,
                }
            )
        return action
