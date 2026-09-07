from odoo import _, api, fields, models
from odoo.exceptions import AccessError


EMAIL_CENTER_GROUPS = (
    "codestra_cc_security.group_cc_scoped_user",
    "codestra_cc_security.group_cc_global_administrator",
)
MAX_EMAIL_CENTER_ITEMS = 20
DEFAULT_EMAIL_CENTER_ITEMS = 8
SMTP_PROFILE_XMLIDS = (
    "codestra_klyrow_smtp.mail_server_klyrow_production",
    "codestra_klyrow_smtp.mail_server_beyvra_production",
)


class CcMailThread(models.Model):
    _inherit = "cc.mail.thread"

    @api.model
    def crm_email_center_snapshot(self, limit=DEFAULT_EMAIL_CENTER_ITEMS):
        """Return a campaign-scoped, read-only snapshot for the CRM pop-out.

        The search intentionally runs as the requesting user. Existing global
        record rules therefore remain the sole authority for campaign scope.
        No message is created, queued, sent, or elevated by this method.
        """
        if not self.env.su and not any(
            self.env.user.has_group(group) for group in EMAIL_CENTER_GROUPS
        ):
            raise AccessError(_("Contact-center email access is required."))

        try:
            bounded_limit = int(limit)
        except (TypeError, ValueError):
            bounded_limit = DEFAULT_EMAIL_CENTER_ITEMS
        bounded_limit = min(max(bounded_limit, 1), MAX_EMAIL_CENTER_ITEMS)

        active_domain = [("state", "in", ["open", "waiting"])]
        threads = self.search(
            active_domain,
            order="write_date desc, id desc",
            limit=bounded_limit,
        )

        profiles = []
        for xmlid in SMTP_PROFILE_XMLIDS:
            server = self.env.ref(xmlid, raise_if_not_found=False)
            if not server:
                continue
            server.invalidate_recordset(
                [
                    "active",
                    "codestra_delivery_ready",
                    "codestra_readiness_message",
                ]
            )
            profiles.append(
                {
                    "name": server.display_name,
                    "active": bool(server.active),
                    "ready": bool(server.codestra_delivery_ready),
                    "message": server.codestra_readiness_message or "",
                }
            )

        return {
            "open_count": self.search_count([("state", "=", "open")]),
            "waiting_count": self.search_count([("state", "=", "waiting")]),
            "delivery_ready": any(profile["ready"] for profile in profiles),
            "compose_enabled": False,
            "profiles": profiles,
            "items": [
                {
                    "id": thread.id,
                    "subject": thread.subject,
                    "campaign": thread.campaign_id.display_name,
                    "route": thread.route_id.display_name,
                    "recipient": thread.recipient,
                    "state": thread.state,
                    "write_date": fields.Datetime.to_string(thread.write_date),
                }
                for thread in threads
            ],
        }
