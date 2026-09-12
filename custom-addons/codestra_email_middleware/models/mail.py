from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

from ..transport import EmailTransportError, enabled

_MAIL_WRITE_CAPABILITY = object()


class MailMail(models.Model):
    _inherit = "mail.mail"

    codestra_email_job_ids = fields.One2many(
        "codestra.email.outbox", "mail_id", readonly=True, groups="base.group_system",
    )
    codestra_email_state = fields.Selection(
        selection=[
            ("requested", "Requested"), ("accepted", "Accepted"),
            ("queued", "Queued"), ("provider_accepted", "Provider accepted"),
            ("delivered", "Delivered"), ("deferred", "Deferred"),
            ("bounced", "Bounced"), ("complained", "Complained"),
            ("suppressed", "Suppressed"), ("rejected", "Rejected"),
            ("failed", "Failed"),
        ],
        readonly=True, copy=False, index=True,
    )
    codestra_middleware_message_id = fields.Char(readonly=True, copy=False, index=True)
    codestra_email_correlation_id = fields.Char(readonly=True, copy=False, index=True)
    codestra_provider_reference = fields.Char(readonly=True, copy=False, index=True)

    def send(self, auto_commit=False, raise_exception=False, post_send_callback=None):
        if not enabled():
            return super().send(
                auto_commit=auto_commit,
                raise_exception=raise_exception,
                post_send_callback=post_send_callback,
            )
        for mail in self.try_lock_for_update().filtered_domain([
            ("state", "=", "outgoing"),
        ]):
            try:
                self.env["codestra.email.outbox"]._enqueue(mail)
            except (EmailTransportError, ValidationError) as error:
                if raise_exception:
                    raise ValidationError(
                        "Email was not queued: %s" % str(error)
                    ) from None
                mail.with_context(
                    _codestra_email_mail_capability=_MAIL_WRITE_CAPABILITY
                ).sudo().write({
                    "state": "exception",
                    "failure_reason": str(error),
                    "codestra_email_state": "rejected",
                })
        return True

    @api.model_create_multi
    def create(self, values_list):
        projection = {
            "codestra_email_state", "codestra_middleware_message_id",
            "codestra_email_correlation_id", "codestra_provider_reference",
        }
        if (
            self.env.context.get("_codestra_email_mail_capability")
            is not _MAIL_WRITE_CAPABILITY
            and any(projection.intersection(values) for values in values_list)
        ):
            raise AccessError("Only the email integration may set delivery state.")
        return super().create(values_list)

    def write(self, values):
        protected = {
            "email_from", "email_to", "email_cc", "recipient_ids", "subject",
            "body_html", "attachment_ids", "mail_message_id", "reply_to",
            "auto_delete", "codestra_email_state", "codestra_middleware_message_id",
            "codestra_email_correlation_id", "codestra_provider_reference",
        }
        if (
            self.env.context.get("_codestra_email_mail_capability")
            is not _MAIL_WRITE_CAPABILITY
            and protected.intersection(values)
            and self.env["codestra.email.outbox"].sudo().search_count([
                ("mail_id", "in", self.ids),
            ])
        ):
            raise AccessError("Queued email content and identity are immutable.")
        return super().write(values)

    def unlink(self):
        if self.env["codestra.email.outbox"].sudo().search_count([
            ("mail_id", "in", self.ids),
        ]):
            raise AccessError("Retain email records with a Middleware delivery history.")
        return super().unlink()
