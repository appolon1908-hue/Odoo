from odoo import fields, models
from odoo.exceptions import AccessError, ValidationError

from ..transport import SmsTransportError, enabled


class SmsSms(models.Model):
    _inherit = "sms.sms"

    codestra_sms_job_ids = fields.One2many(
        "codestra.sms.outbox", "sms_id", readonly=True, groups="base.group_system",
    )

    def _split_by_api(self):
        # The native send() and scheduler both reach _send. No IAP object or
        # account should be created when the Middleware integration owns SMS.
        yield None, self

    def _send(self, unlink_failed=False, unlink_sent=True, raise_exception=False):
        for sms in self.try_lock_for_update().filtered_domain([
            ("state", "=", "outgoing"), ("to_delete", "=", False),
        ]):
            try:
                if not enabled():
                    raise SmsTransportError("SMS_INTEGRATION_DISABLED")
                self.env["codestra.sms.outbox"]._enqueue(sms)
            except (SmsTransportError, ValidationError) as error:
                if raise_exception:
                    raise ValidationError("SMS was not queued: %s" % str(error)) from None
                sms._update_sms_state_and_trackers("error", "sms_server")
        # Submission is performed only by the outbox cron after this transaction
        # commits. Keep native SMS and notification records for reconciliation.
        return True

    def write(self, values):
        protected = {"number", "body", "uuid", "mail_message_id", "partner_id", "to_delete"}
        if protected.intersection(values) and self.env["codestra.sms.outbox"].sudo().search_count([
            ("sms_id", "in", self.ids),
        ]):
            raise AccessError("Queued SMS content and identity are immutable.")
        return super().write(values)

    def unlink(self):
        if self.env["codestra.sms.outbox"].sudo().search_count([("sms_id", "in", self.ids)]):
            raise AccessError("Retain SMS records with a Middleware delivery history.")
        return super().unlink()

    def action_set_canceled(self):
        if self.env["codestra.sms.outbox"].sudo().search_count([
            ("sms_id", "in", self.ids), ("state", "in", ("indeterminate", "reconcile", "done")),
        ]):
            raise ValidationError("This SMS has entered submission. Check its delivery result before cancelling.")
        return super().action_set_canceled()
