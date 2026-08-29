import ast
import base64
import hashlib
import logging
from datetime import timedelta
from email.utils import getaddresses

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import email_normalize, html_sanitize


_logger = logging.getLogger(__name__)

APPROVED_DOMAINS = {
    "beyvra.com", "breero.com", "breero.shop", "codestra.agency",
    "codestra.cloud", "codestra.co", "codestra.digital", "codestra.media",
    "klyrow.com", "kyqra.com", "moneybee.loan", "moneybeeloan.com",
    "nativoenglish.com", "telnexa.co",
}
ALLOWED_RECIPIENTS = {
    f"{local_part}@{domain}"
    for domain in APPROVED_DOMAINS
    for local_part in ("support", "billing")
}
ALLOWED_RECIPIENTS.update({
    f"{local_part}@{domain}"
    for domain in {
        "beyvra.com", "breero.com", "booked4seasons.com", "codestra.co",
        "klyrow.com", "kyqra.com", "telnexa.co",
    }
    for local_part in ("support", "admin")
})
PROHIBITED_EXTENSIONS = {
    ".apk", ".app", ".bat", ".cmd", ".com", ".dll", ".dmg", ".exe",
    ".hta", ".jar", ".js", ".jse", ".lnk", ".msi", ".ps1", ".scr",
    ".vbe", ".vbs",
}
SAFE_MIME_PREFIXES = ("application/pdf", "image/", "text/")
MAX_MESSAGE_BYTES = 20 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024


class MailBrand(models.Model):
    _name = "codestra.mail.brand"
    _description = "Shared Inbox Brand"
    _order = "name"

    name = fields.Char(required=True, index=True)
    code = fields.Char(required=True, index=True)
    domain = fields.Char(required=True, index=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company,
        ondelete="restrict",
    )
    active = fields.Boolean(default=True)
    team_ids = fields.One2many("codestra.mail.team", "brand_id")

    _code_unique = models.UniqueIndex("(code)")
    _domain_unique = models.UniqueIndex("(domain)")

    @api.constrains("domain")
    def _check_domain(self):
        for record in self:
            normalized = (record.domain or "").strip().lower()
            if not normalized or "@" in normalized or normalized != record.domain:
                raise ValidationError(_("Brand domain must be a lowercase domain name."))


class MailQueueType(models.Model):
    _name = "codestra.mail.queue.type"
    _description = "Shared Inbox Queue Type"
    _order = "sequence, code"

    name = fields.Char(required=True)
    code = fields.Selection(
        [
            ("SUPPORT", "Support"),
            ("BILLING", "Billing / Accounting"),
            ("ADMINISTRATION", "Administration (legacy)"),
        ],
        required=True,
    )
    sequence = fields.Integer(default=10)
    stage_ids = fields.One2many("codestra.mail.stage", "queue_type_id")

    _code_unique = models.UniqueIndex("(code)")


class MailStage(models.Model):
    _name = "codestra.mail.stage"
    _description = "Shared Inbox Stage"
    _order = "queue_type_id, sequence, id"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    queue_type_id = fields.Many2one("codestra.mail.queue.type", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    is_closed = fields.Boolean(default=False)

    _code_type_unique = models.UniqueIndex("(code, queue_type_id)")


class MailTeam(models.Model):
    _name = "codestra.mail.team"
    _description = "Shared Inbox Team"
    _inherit = ["mail.alias.mixin", "mail.thread"]
    _order = "brand_id, queue_type_id"

    name = fields.Char(required=True, tracking=True)
    brand_id = fields.Many2one("codestra.mail.brand", required=True, ondelete="restrict", tracking=True)
    queue_type_id = fields.Many2one("codestra.mail.queue.type", required=True, ondelete="restrict", tracking=True)
    company_id = fields.Many2one(related="brand_id.company_id", store=True, index=True)
    member_ids = fields.Many2many("res.users", "codestra_mail_team_member_rel", string="Members")
    manager_ids = fields.Many2many("res.users", "codestra_mail_team_manager_rel", string="Managers")
    auditor_ids = fields.Many2many("res.users", "codestra_mail_team_auditor_rel", string="Auditors")
    conversation_ids = fields.One2many("codestra.mail.conversation", "team_id")
    active = fields.Boolean(default=True)
    external_delivery_enabled = fields.Boolean(default=False, readonly=True)

    _brand_queue_unique = models.UniqueIndex("(brand_id, queue_type_id)")

    def _alias_get_creation_values(self):
        values = super()._alias_get_creation_values()
        values.update({
            "alias_model_id": self.env["ir.model"]._get("codestra.mail.conversation").id,
            "alias_contact": "everyone",
        })
        if self.id:
            values["alias_defaults"] = defaults = ast.literal_eval(self.alias_defaults or "{}")
            defaults["team_id"] = self.id
        return values

    @api.constrains("alias_name", "alias_domain_id", "queue_type_id", "brand_id")
    def _check_exact_alias(self):
        for team in self.filtered(lambda t: t.alias_name and t.alias_domain_id):
            address = f"{team.alias_name}@{team.alias_domain_id.name}".lower()
            expected_local = {
                "SUPPORT": "support",
                "BILLING": "billing",
                "ADMINISTRATION": "admin",
            }.get(team.queue_type_id.code)
            if address not in ALLOWED_RECIPIENTS:
                raise ValidationError(_("Only an approved exact shared-inbox recipient is allowed."))
            if team.alias_name != expected_local or team.alias_domain_id.name != team.brand_id.domain:
                raise ValidationError(_("Alias local-part, brand domain, and queue type must match exactly."))


class MailSlaPolicy(models.Model):
    _name = "codestra.mail.sla.policy"
    _description = "Shared Inbox SLA Policy"

    name = fields.Char(required=True)
    queue_type_id = fields.Many2one("codestra.mail.queue.type", required=True, ondelete="cascade")
    first_response_hours = fields.Float(required=True)
    unassigned_alert_minutes = fields.Integer(required=True, default=30)
    active = fields.Boolean(default=True)

    _queue_type_unique = models.UniqueIndex("(queue_type_id)")


class MailSenderAllowlist(models.Model):
    _name = "codestra.mail.sender.allowlist"
    _description = "Shared Inbox Sender Allowlist"

    team_id = fields.Many2one("codestra.mail.team", required=True, ondelete="cascade", index=True)
    sender = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)

    _team_unique = models.UniqueIndex("(team_id)")
    _sender_unique = models.UniqueIndex("(sender)")

    @api.constrains("sender", "team_id")
    def _check_sender(self):
        for record in self:
            sender = email_normalize(record.sender or "")
            expected = record.team_id.alias_id.alias_full_name
            if not sender or sender != expected or sender not in ALLOWED_RECIPIENTS:
                raise ValidationError(_("Sender must equal the team's exact approved alias."))


class MailConversation(models.Model):
    _name = "codestra.mail.conversation"
    _description = "Shared Inbox Conversation"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "write_date desc, id desc"
    _primary_email = "sender"

    name = fields.Char(required=True, tracking=True)
    team_id = fields.Many2one("codestra.mail.team", required=True, ondelete="restrict", tracking=True, index=True)
    brand_id = fields.Many2one(related="team_id.brand_id", store=True, index=True)
    queue_type_id = fields.Many2one(related="team_id.queue_type_id", store=True, index=True)
    company_id = fields.Many2one(related="team_id.company_id", store=True, index=True)
    stage_id = fields.Many2one("codestra.mail.stage", required=True, ondelete="restrict", tracking=True, index=True)
    user_id = fields.Many2one("res.users", string="Assigned To", tracking=True, index=True)
    sender = fields.Char(required=True, index=True)
    recipient = fields.Char(required=True, index=True, readonly=True)
    source_message_id = fields.Char(required=True, index=True, readonly=True)
    correlation_id = fields.Char(required=True, index=True, readonly=True)
    first_response_due = fields.Datetime(readonly=True)
    first_response_at = fields.Datetime(readonly=True, tracking=True)
    active = fields.Boolean(default=True)

    _source_message_unique = models.UniqueIndex("(source_message_id)")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            team = self.env["codestra.mail.team"].browse(vals.get("team_id"))
            if team and not vals.get("stage_id"):
                vals["stage_id"] = self.env["codestra.mail.stage"].search(
                    [("queue_type_id", "=", team.queue_type_id.id)], order="sequence, id", limit=1
                ).id
            if team and not vals.get("recipient"):
                vals["recipient"] = team.alias_id.alias_full_name
            if team and not vals.get("first_response_due"):
                policy = self.env["codestra.mail.sla.policy"].search(
                    [("queue_type_id", "=", team.queue_type_id.id), ("active", "=", True)], limit=1
                )
                vals["first_response_due"] = fields.Datetime.now() + timedelta(hours=policy.first_response_hours or 0)
        return super().create(vals_list)

    def write(self, vals):
        protected = {"team_id", "brand_id", "queue_type_id", "recipient"}.intersection(vals)
        if protected and not (
            self.env.user.has_group("codestra_mail_inbox.group_mail_support_manager")
            or self.env.user.has_group("codestra_mail_inbox.group_mail_admin_manager")
            or self.env.user.has_group("base.group_system")
        ):
            raise AccessError(_("Only an authorized manager may change the queue destination."))
        if protected:
            for record in self:
                self.env["codestra.mail.audit"].sudo().create({
                    "event_type": "DESTINATION_CHANGE",
                    "conversation_id": record.id,
                    "actor_id": self.env.uid,
                    "metadata_hash": hashlib.sha256(repr(sorted(vals)).encode()).hexdigest(),
                })
        return super().write(vals)

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        custom_values = dict(custom_values or {})
        team = self.env["codestra.mail.team"].browse(custom_values.get("team_id")).exists()
        if not team:
            raise ValidationError(_("Inbound alias is not bound to a shared-inbox team."))
        recipients = {
            email_normalize(addr) for _, addr in getaddresses(
                [msg_dict.get("to", ""), msg_dict.get("cc", ""), msg_dict.get("delivered_to", "")]
            ) if email_normalize(addr)
        }
        expected = team.alias_id.alias_full_name
        if expected not in recipients:
            raise ValidationError(_("Inbound message does not target the exact bound alias."))
        custom_values.update({
            "name": msg_dict.get("subject") or _("No Subject"),
            "sender": email_normalize(msg_dict.get("email_from") or "") or msg_dict.get("email_from"),
            "recipient": expected,
            "source_message_id": msg_dict.get("message_id") or hashlib.sha256(repr(msg_dict).encode()).hexdigest(),
            "correlation_id": msg_dict.get("correlation_id") or hashlib.sha256((msg_dict.get("message_id") or expected).encode()).hexdigest(),
        })
        return super().message_new(msg_dict, custom_values=custom_values)

    def prepare_outbound(self, idempotency_key, supplied_from=None):
        self.ensure_one()
        sender_rule = self.env["codestra.mail.sender.allowlist"].search(
            [("team_id", "=", self.team_id.id), ("active", "=", True)], limit=1
        )
        if not sender_rule:
            raise ValidationError(_("No approved sender exists for this queue."))
        supplied = email_normalize(supplied_from or sender_rule.sender)
        if supplied != sender_rule.sender:
            raise ValidationError(_("The From address cannot be overridden."))
        if not idempotency_key:
            raise ValidationError(_("Outbound idempotency key is required."))
        return {
            "conversation_id": self.id,
            "queue_id": self.team_id.id,
            "sender": sender_rule.sender,
            "idempotency_key": idempotency_key,
            "external_delivery_enabled": False,
        }


class MailInboundEvent(models.Model):
    _name = "codestra.mail.inbound.event"
    _description = "Shared Inbox Inbound Event Ledger"
    _order = "create_date desc"

    event_id = fields.Char(required=True, index=True, readonly=True)
    idempotency_key = fields.Char(required=True, index=True, readonly=True)
    correlation_id = fields.Char(required=True, index=True, readonly=True)
    message_id = fields.Char(required=True, index=True, readonly=True)
    recipient = fields.Char(required=True, index=True, readonly=True)
    payload_hash = fields.Char(required=True, readonly=True)
    received_at = fields.Datetime(required=True, readonly=True)
    conversation_id = fields.Many2one("codestra.mail.conversation", readonly=True, ondelete="set null")
    state = fields.Selection(
        [("PROCESSING", "Processing"), ("PROCESSED", "Processed"), ("REJECTED", "Rejected")],
        required=True, default="PROCESSING", readonly=True,
    )

    _event_unique = models.UniqueIndex("(event_id)")
    _idempotency_unique = models.UniqueIndex("(idempotency_key)")
    _message_recipient_unique = models.UniqueIndex("(message_id, recipient)")

    @api.model
    def ingest_event(self, payload):
        if not self.env.su and not self.env.user.has_group(
            "codestra_mail_inbox.group_mail_ingestion_service"
        ):
            raise AccessError(_("Dedicated middleware ingestion role is required."))
        ledger_model = self.sudo()
        required = {"event_id", "idempotency_key", "correlation_id", "timestamp", "message_id", "recipient", "sender", "subject"}
        missing = sorted(required.difference(payload))
        if missing:
            raise ValidationError(_("Missing required event fields: %s") % ", ".join(missing))
        if payload.get("authenticated_identity") != "codestra-middleware" or payload.get("signature_valid") is not True:
            raise AccessError(_("Authenticated middleware identity and verified signature are required."))
        timestamp = fields.Datetime.to_datetime(payload["timestamp"])
        now = fields.Datetime.now()
        if not timestamp or abs((now - timestamp).total_seconds()) > 300:
            raise ValidationError(_("Event timestamp is outside the replay window."))
        if ledger_model.search_count([("event_id", "=", payload["event_id"])]):
            raise ValidationError(_("Replayed event ID rejected."))
        if ledger_model.search_count([("idempotency_key", "=", payload["idempotency_key"])]):
            raise ValidationError(_("Duplicate idempotency key rejected."))
        recipient = email_normalize(payload["recipient"])
        sender = email_normalize(payload["sender"])
        if recipient not in ALLOWED_RECIPIENTS or not sender:
            raise ValidationError(_("Unknown recipient or invalid sender."))
        team = ledger_model.env["codestra.mail.team"].search([("alias_id.alias_full_name", "=", recipient)], limit=2)
        if len(team) != 1:
            raise ValidationError(_("Recipient must resolve to exactly one queue."))
        raw_size = int(payload.get("raw_size") or 0)
        if raw_size > MAX_MESSAGE_BYTES:
            raise ValidationError(_("Message exceeds the configured size limit."))
        payload_hash = hashlib.sha256(repr(sorted((k, str(v)) for k, v in payload.items() if k not in {"body_html", "body_text", "attachments"})).encode()).hexdigest()
        ledger = ledger_model.create({
            "event_id": payload["event_id"],
            "idempotency_key": payload["idempotency_key"],
            "correlation_id": payload["correlation_id"],
            "message_id": payload["message_id"],
            "recipient": recipient,
            "payload_hash": payload_hash,
            "received_at": timestamp,
        })
        refs = [payload.get("in_reply_to")] + list(payload.get("references") or [])
        parent = ledger_model.search([
            ("message_id", "in", [ref for ref in refs if ref]),
            ("recipient", "=", recipient),
            ("state", "=", "PROCESSED"),
        ], order="id desc", limit=1)
        conversation = parent.conversation_id
        if not conversation:
            conversation = ledger_model.env["codestra.mail.conversation"].create({
                "name": payload["subject"] or _("No Subject"),
                "team_id": team.id,
                "sender": sender,
                "recipient": recipient,
                "source_message_id": payload["message_id"],
                "correlation_id": payload["correlation_id"],
            })
        attachment_ids = []
        for item in payload.get("attachments") or []:
            name = (item.get("filename") or "attachment").strip()
            mimetype = (item.get("mimetype") or "application/octet-stream").lower()
            try:
                content = base64.b64decode(item.get("content_base64") or "", validate=True)
            except Exception as exc:
                raise ValidationError(_("Attachment encoding is invalid.")) from exc
            suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if len(content) > MAX_ATTACHMENT_BYTES:
                raise ValidationError(_("Attachment exceeds the configured size limit."))
            if suffix in PROHIBITED_EXTENSIONS or not mimetype.startswith(SAFE_MIME_PREFIXES):
                ledger_model.env["codestra.mail.quarantine"].create({
                    "filename_hash": hashlib.sha256(name.encode()).hexdigest(),
                    "content_hash": hashlib.sha256(content).hexdigest(),
                    "size": len(content),
                    "reason": "PROHIBITED_TYPE",
                    "correlation_id": payload["correlation_id"],
                })
                continue
            attachment_ids.append(ledger_model.env["ir.attachment"].create({
                "name": name,
                "datas": base64.b64encode(content),
                "mimetype": mimetype,
                "res_model": conversation._name,
                "res_id": conversation.id,
            }).id)
        body = html_sanitize(payload.get("body_html") or payload.get("body_text") or "", sanitize_tags=True, sanitize_attributes=True)
        conversation.message_post(
            # html_sanitize above is the single trust transition for message HTML.
            body=Markup(body),  # nosec B704
            message_type="comment", subtype_xmlid="mail.mt_comment",
            email_from=sender, attachment_ids=attachment_ids,
        )
        ledger.write({"conversation_id": conversation.id, "state": "PROCESSED"})
        ledger_model.env["codestra.mail.audit"].create({
            "event_type": "INBOUND_PROCESSED",
            "conversation_id": conversation.id,
            "actor_id": self.env.uid,
            "metadata_hash": payload_hash,
        })
        _logger.info("shared_inbox_event_processed event_hash=%s correlation_hash=%s", hashlib.sha256(payload["event_id"].encode()).hexdigest(), hashlib.sha256(payload["correlation_id"].encode()).hexdigest())
        return conversation


class MailQuarantine(models.Model):
    _name = "codestra.mail.quarantine"
    _description = "Shared Inbox Attachment Quarantine Ledger"
    _order = "create_date desc"

    filename_hash = fields.Char(required=True, readonly=True)
    content_hash = fields.Char(required=True, readonly=True)
    size = fields.Integer(required=True, readonly=True)
    reason = fields.Char(required=True, readonly=True)
    correlation_id = fields.Char(required=True, readonly=True)


class MailAudit(models.Model):
    _name = "codestra.mail.audit"
    _description = "Shared Inbox Audit Event"
    _order = "create_date desc"

    event_type = fields.Char(required=True, readonly=True, index=True)
    conversation_id = fields.Many2one("codestra.mail.conversation", readonly=True, ondelete="set null", index=True)
    actor_id = fields.Many2one("res.users", required=True, readonly=True, ondelete="restrict")
    metadata_hash = fields.Char(required=True, readonly=True)
