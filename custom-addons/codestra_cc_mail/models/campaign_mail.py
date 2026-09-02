import base64
import hashlib
import json
import re
import uuid
from email.utils import getaddresses

from markupsafe import Markup

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools import email_normalize, html_sanitize


MAIL_ROUTE_WRITE_CAPABILITY = object()
MAIL_EVENT_WRITE_CAPABILITY = object()
MAIL_QUARANTINE_WRITE_CAPABILITY = object()
MAIL_DISTRIBUTION_WRITE_CAPABILITY = object()
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
LOCAL_PART_PATTERN = re.compile(r"^[a-z0-9]+(?:[._+-][a-z0-9]+)*$")
DOMAIN_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)
PROHIBITED_EXTENSIONS = {
    ".apk",
    ".app",
    ".bat",
    ".cmd",
    ".com",
    ".dll",
    ".dmg",
    ".exe",
    ".hta",
    ".jar",
    ".js",
    ".jse",
    ".lnk",
    ".msi",
    ".ps1",
    ".scr",
    ".vbe",
    ".vbs",
}
SAFE_MIME_PREFIXES = ("application/pdf", "image/", "text/")
MAX_MESSAGE_BYTES = 20 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024


def _canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(value):
    encoded = value if isinstance(value, bytes) else str(value).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalized_address(value):
    return (email_normalize(value or "") or "").lower()


def _canonical_from_legacy(env, legacy_campaign_id):
    """Return only the immutable canonical tag for an accessible legacy owner.

    Existing modules still post chatter under ``call.center.campaign``. The
    narrow elevation is limited to an indexed FK lookup and returns no business
    payload. The caller has already resolved the linked resource through its
    current environment; the resulting ID is immediately re-applied as a global
    record-rule tag.
    """
    return (
        env["cc.campaign"]
        .with_user(SUPERUSER_ID)
        .search([("legacy_campaign_id", "=", legacy_campaign_id)], limit=1)
    )


def _resource_campaign(env, model_name, record_id):
    if not model_name or not record_id:
        return env["cc.campaign"]
    try:
        model = env[model_name]
    except KeyError:
        return env["cc.campaign"]
    record = model.browse(int(record_id)).exists()
    # Generic mail models must never become an alternate route around the
    # linked business record's own ACLs and record rules.  The global mail
    # rules are intentionally not applied on create so legacy modules can
    # continue posting chatter before canonical memberships are reconciled;
    # this explicit check preserves fail-closed source ownership.
    record.check_access("read")
    if not record:
        return env["cc.campaign"]
    if record._name == "cc.campaign":
        return record
    if record._name == "call.center.campaign":
        return _canonical_from_legacy(env, record.id)
    if "campaign_id" in record._fields:
        campaign_field = record._fields["campaign_id"]
        if campaign_field.type != "many2one" or not record.campaign_id:
            return env["cc.campaign"]
        if campaign_field.comodel_name == "cc.campaign":
            return record.campaign_id
        if campaign_field.comodel_name == "call.center.campaign":
            return _canonical_from_legacy(env, record.campaign_id.id)
    return env["cc.campaign"]


def _tag_create_values(env, original, model_field, id_field):
    values = dict(original)
    campaign = _resource_campaign(env, values.get(model_field), values.get(id_field))
    supplied = values.get("cc_campaign_id")
    if campaign:
        if supplied and supplied != campaign.id:
            raise AccessError(_("Campaign tags are derived from the linked resource."))
        values["cc_campaign_id"] = campaign.id
    elif supplied:
        raise AccessError(_("A campaign tag cannot be supplied without a scoped resource."))
    return values


def _prepare_binding_write(record, values, model_field, id_field):
    if "cc_campaign_id" in values:
        raise AccessError(_("Campaign tags are server-managed and immutable."))
    if not ({model_field, id_field} & set(values)):
        return values
    model_name = values.get(model_field, record[model_field])
    record_id = values.get(id_field, record[id_field])
    campaign = _resource_campaign(record.env, model_name, record_id)
    if record.cc_campaign_id and campaign != record.cc_campaign_id:
        raise AccessError(_("A campaign-scoped mail record cannot be moved."))
    prepared = dict(values)
    if campaign:
        prepared["cc_campaign_id"] = campaign.id
    return prepared


class CcCampaign(models.Model):
    _inherit = "cc.campaign"

    email_route_ids = fields.One2many("cc.mail.route", "campaign_id")
    mail_thread_ids = fields.One2many("cc.mail.thread", "campaign_id")


class CcMailRoute(models.Model):
    _name = "cc.mail.route"
    _description = "Campaign-Owned Mail Route"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "campaign_id, route_class, id"

    name = fields.Char(required=True)
    campaign_code = fields.Char(
        related="campaign_id.code", store=True, readonly=True, index=True
    )
    route_class = fields.Selection(
        [
            ("leads", "Leads"),
            ("sales", "Sales"),
            ("support", "Support"),
            ("billing", "Billing"),
            ("callbacks", "Callbacks"),
            ("supervisor", "Supervisor"),
            ("qa", "Quality Assurance"),
        ],
        required=True,
        index=True,
    )
    direction = fields.Selection(
        [("inbound", "Inbound"), ("outbound", "Outbound"), ("both", "Both")],
        required=True,
        default="both",
        index=True,
    )
    local_part = fields.Char(required=True, index=True)
    domain = fields.Char(required=True, index=True)
    address = fields.Char(compute="_compute_address", store=True, index=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("pending_approval", "Pending Approval"),
            ("testing", "Staging Testing"),
            ("provisioned_disabled", "Provisioned Disabled"),
            ("blocked", "Blocked"),
            ("retired", "Retired"),
        ],
        required=True,
        default="draft",
        copy=False,
        index=True,
    )
    source_ticket = fields.Char(required=True, copy=False, index=True)
    requested_by_id = fields.Many2one(
        "res.users",
        required=True,
        default=lambda self: self.env.user,
        ondelete="restrict",
        copy=False,
    )
    approved_by_id = fields.Many2one(
        "res.users", ondelete="restrict", copy=False, readonly=True
    )
    approved_at = fields.Datetime(copy=False, readonly=True)
    odoo_alias_id = fields.Many2one(
        "mail.alias", ondelete="restrict", copy=False, readonly=True
    )
    legacy_team_id = fields.Many2one(
        "codestra.mail.team", ondelete="restrict", copy=False, readonly=True
    )
    inbound_mutation_enabled = fields.Boolean(default=False, readonly=True, copy=False)
    external_send_enabled = fields.Boolean(default=False, readonly=True, copy=False)
    sender_identity_id = fields.One2many("cc.mail.sender.identity", "route_id")
    distribution_group_id = fields.One2many("cc.mail.distribution.group", "route_id")

    _address_unique = models.Constraint(
        "unique(address)", "A mail address may route to only one campaign."
    )
    _campaign_route_class_unique = models.Constraint(
        "unique(campaign_id, route_class)",
        "A campaign may configure each mail route class only once.",
    )

    @api.depends("local_part", "domain")
    def _compute_address(self):
        for route in self:
            local_part = (route.local_part or "").strip().lower()
            domain = (route.domain or "").strip().lower()
            route.address = f"{local_part}@{domain}" if local_part and domain else False

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            if values.get("state", "draft") != "draft":
                raise AccessError(_("Mail routes must begin in draft state."))
            if values.get("inbound_mutation_enabled") or values.get(
                "external_send_enabled"
            ):
                raise AccessError(_("Live mail capabilities remain disabled."))
            local_part = (values.get("local_part") or "").strip().lower()
            domain = (values.get("domain") or "").strip().lower()
            address = f"{local_part}@{domain}" if local_part and domain else False
            duplicate_domain = [
                "|",
                ("address", "=", address),
                "&",
                ("campaign_id", "=", values.get("campaign_id")),
                ("route_class", "=", values.get("route_class")),
            ]
            if address and self.search_count(duplicate_domain, limit=1):
                raise ValidationError(
                    _("The campaign route class or mail address already exists.")
                )
        return super().create(values_list)

    def write(self, values):
        protected = {
            "campaign_id",
            "local_part",
            "domain",
            "route_class",
            "odoo_alias_id",
            "legacy_team_id",
            "inbound_mutation_enabled",
            "external_send_enabled",
        }
        if protected & set(values):
            if any(route.state not in {"draft", "pending_approval"} for route in self):
                raise AccessError(_("Approved mail-route identity is immutable."))
            if values.get("inbound_mutation_enabled") or values.get(
                "external_send_enabled"
            ):
                raise AccessError(_("Live mail capabilities remain disabled."))
        if (
            "state" in values
            and self.env.context.get("_cc_mail_route_capability")
            is not MAIL_ROUTE_WRITE_CAPABILITY
        ):
            raise AccessError(_("Mail-route state requires the governed workflow."))
        return super().write(values)

    def unlink(self):
        if any(route.state != "draft" for route in self):
            raise AccessError(_("Approved mail-route evidence cannot be deleted."))
        return super().unlink()

    @api.constrains(
        "local_part",
        "domain",
        "address",
        "campaign_id",
        "odoo_alias_id",
        "legacy_team_id",
        "inbound_mutation_enabled",
        "external_send_enabled",
    )
    def _check_route(self):
        for route in self:
            local_part = (route.local_part or "").strip().lower()
            domain = (route.domain or "").strip().lower()
            if local_part != route.local_part or not LOCAL_PART_PATTERN.fullmatch(
                local_part
            ):
                raise ValidationError(_("Alias local parts must be normalized lowercase."))
            if domain != route.domain or not DOMAIN_PATTERN.fullmatch(domain):
                raise ValidationError(_("Alias domains must be normalized lowercase domains."))
            if route.address != f"{local_part}@{domain}":
                raise ValidationError(_("The mail-route address is not canonical."))
            if route.inbound_mutation_enabled or route.external_send_enabled:
                raise ValidationError(_("Live mail capabilities are not available."))
            if route.campaign_id.environment == "production" and route.state in {
                "testing",
                "provisioned_disabled",
            }:
                raise ValidationError(_("This branch cannot configure production mail."))
            if route.odoo_alias_id and _normalized_address(
                route.odoo_alias_id.alias_full_name
            ) != route.address:
                raise ValidationError(_("The Odoo alias does not match the campaign route."))
            if route.legacy_team_id and _normalized_address(
                route.legacy_team_id.alias_id.alias_full_name
            ) != route.address:
                raise ValidationError(_("The legacy team does not match the campaign route."))

    def _require_configuration_authority(self):
        allowed = self.env.user.has_group(
            "codestra_cc_security.group_cc_global_administrator"
        ) or self.env.user.has_group(
            "codestra_cc_security.group_cc_campaign_configuration_manager"
        )
        if not allowed:
            raise AccessError(_("Campaign mail configuration permission is required."))

    def action_submit(self):
        self._require_configuration_authority()
        for route in self:
            if route.state != "draft":
                raise ValidationError(_("Only draft mail routes can be submitted."))
            route.with_context(
                _cc_mail_route_capability=MAIL_ROUTE_WRITE_CAPABILITY
            ).write({"state": "pending_approval"})
        return True

    def action_approve_for_staging(self):
        if not self.env.user.has_group(
            "codestra_cc_security.group_cc_global_administrator"
        ):
            raise AccessError(_("Global contact-center approval is required."))
        for route in self:
            if route.state != "pending_approval":
                raise ValidationError(_("Only submitted mail routes can be approved."))
            if route.requested_by_id == self.env.user:
                raise AccessError(_("The route requester cannot approve the same route."))
            route.with_context(
                _cc_mail_route_capability=MAIL_ROUTE_WRITE_CAPABILITY
            ).write(
                {
                    "state": "testing",
                    "approved_by_id": self.env.user.id,
                    "approved_at": fields.Datetime.now(),
                }
            )
            route.campaign_id.write(
                {"scope_version": route.campaign_id.scope_version + 1}
            )
        return True


class CcMailSenderIdentity(models.Model):
    _name = "cc.mail.sender.identity"
    _description = "Campaign Mail Sender Identity"
    _inherit = "cc.campaign.scoped.mixin"

    route_id = fields.Many2one(
        "cc.mail.route", required=True, ondelete="restrict", index=True
    )
    display_name = fields.Char(required=True)
    from_address = fields.Char(required=True, index=True)
    reply_to_address = fields.Char(required=True)
    signature_html = fields.Html(sanitize=True)
    legal_footer_html = fields.Html(sanitize=True)
    tracking_domain = fields.Char()
    state = fields.Selection(
        [
            ("pending_readback", "Pending Read-Back"),
            ("matched", "Read-Back Matched"),
            ("mismatch", "Mismatch"),
            ("blocked", "Blocked"),
        ],
        required=True,
        default="pending_readback",
        copy=False,
        index=True,
    )
    read_back_evidence_hash = fields.Char(size=64, readonly=True, copy=False)
    provider_identity_hash = fields.Char(size=64, readonly=True, copy=False)
    external_send_enabled = fields.Boolean(default=False, readonly=True, copy=False)

    _route_unique = models.Constraint(
        "unique(route_id)", "A campaign mail route has one sender identity."
    )

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            if values.get("state", "pending_readback") != "pending_readback":
                raise AccessError(_("Sender identities require staging read-back."))
            if values.get("external_send_enabled"):
                raise AccessError(_("External email delivery remains disabled."))
        return super().create(values_list)

    def write(self, values):
        protected = {
            "route_id",
            "campaign_id",
            "from_address",
            "reply_to_address",
            "state",
            "read_back_evidence_hash",
            "provider_identity_hash",
            "external_send_enabled",
        }
        if protected & set(values) and self.env.context.get(
            "_cc_mail_distribution_capability"
        ) is not MAIL_DISTRIBUTION_WRITE_CAPABILITY:
            raise AccessError(_("Sender identity is governed read-back evidence."))
        return super().write(values)

    def unlink(self):
        raise AccessError(_("Sender identity evidence cannot be deleted."))

    @api.constrains(
        "route_id",
        "campaign_id",
        "from_address",
        "reply_to_address",
        "tracking_domain",
        "external_send_enabled",
    )
    def _check_identity(self):
        for identity in self:
            if identity.route_id.campaign_id != identity.campaign_id:
                raise ValidationError(_("Sender identity and route campaigns differ."))
            if _normalized_address(identity.from_address) != identity.route_id.address:
                raise ValidationError(_("Outbound From must equal the approved route."))
            if _normalized_address(identity.reply_to_address) != identity.route_id.address:
                raise ValidationError(_("Reply-To must equal the approved route."))
            if identity.tracking_domain:
                domain = identity.tracking_domain.strip().lower()
                if domain != identity.tracking_domain or not DOMAIN_PATTERN.fullmatch(domain):
                    raise ValidationError(_("Tracking domains must be normalized."))
            if identity.external_send_enabled:
                raise ValidationError(_("External email delivery remains disabled."))

    def action_record_staging_readback(
        self, evidence_hash, provider_identity_hash, matched=True
    ):
        self.env["cc.mail.inbound.event"]._require_ingestion_service()
        for value in (evidence_hash, provider_identity_hash):
            if not SHA256_PATTERN.fullmatch((value or "").lower()):
                raise ValidationError(_("Sender read-back evidence must be SHA-256."))
        self.with_context(
            _cc_mail_distribution_capability=MAIL_DISTRIBUTION_WRITE_CAPABILITY
        ).write(
            {
                "state": "matched" if matched else "mismatch",
                "read_back_evidence_hash": evidence_hash.lower(),
                "provider_identity_hash": provider_identity_hash.lower(),
            }
        )
        return True


class CcMailDistributionGroup(models.Model):
    _name = "cc.mail.distribution.group"
    _description = "Campaign Mail Distribution Group"
    _inherit = "cc.campaign.scoped.mixin"

    name = fields.Char(required=True)
    route_id = fields.Many2one(
        "cc.mail.route", required=True, ondelete="restrict", index=True
    )
    external_group_key = fields.Char(required=True, index=True)
    state = fields.Selection(
        [
            ("pending_readback", "Pending Read-Back"),
            ("matched", "Read-Back Matched"),
            ("mismatch", "Mismatch"),
            ("blocked", "Blocked"),
        ],
        required=True,
        default="pending_readback",
        copy=False,
        index=True,
    )
    read_back_evidence_hash = fields.Char(size=64, readonly=True, copy=False)
    external_delivery_enabled = fields.Boolean(default=False, readonly=True, copy=False)
    membership_ids = fields.One2many(
        "cc.mail.distribution.membership", "distribution_group_id"
    )

    _route_unique = models.Constraint(
        "unique(route_id)", "A campaign mail route has one distribution group."
    )
    _external_group_key_unique = models.Constraint(
        "unique(external_group_key)", "Distribution group keys must be unique."
    )

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            if values.get("state", "pending_readback") != "pending_readback":
                raise AccessError(_("Distribution groups require staging read-back."))
            if values.get("external_delivery_enabled"):
                raise AccessError(_("External distribution remains disabled."))
        return super().create(values_list)

    def write(self, values):
        protected = {
            "route_id",
            "campaign_id",
            "external_group_key",
            "state",
            "read_back_evidence_hash",
            "external_delivery_enabled",
        }
        if protected & set(values) and self.env.context.get(
            "_cc_mail_distribution_capability"
        ) is not MAIL_DISTRIBUTION_WRITE_CAPABILITY:
            raise AccessError(_("Distribution groups require governed read-back."))
        return super().write(values)

    def unlink(self):
        raise AccessError(_("Distribution group evidence cannot be deleted."))

    @api.constrains("route_id", "campaign_id", "external_delivery_enabled")
    def _check_group(self):
        for group in self:
            if group.route_id.campaign_id != group.campaign_id:
                raise ValidationError(_("Distribution group and route campaigns differ."))
            if group.external_delivery_enabled:
                raise ValidationError(_("External distribution remains disabled."))

    def action_record_staging_readback(self, evidence_hash, matched=True):
        self.env["cc.mail.inbound.event"]._require_ingestion_service()
        if not SHA256_PATTERN.fullmatch((evidence_hash or "").lower()):
            raise ValidationError(_("Distribution read-back evidence must be SHA-256."))
        self.with_context(
            _cc_mail_distribution_capability=MAIL_DISTRIBUTION_WRITE_CAPABILITY
        ).write(
            {
                "state": "matched" if matched else "mismatch",
                "read_back_evidence_hash": evidence_hash.lower(),
            }
        )
        return True


class CcMailDistributionMembership(models.Model):
    _name = "cc.mail.distribution.membership"
    _description = "Campaign Distribution Membership Read-Back"
    _inherit = "cc.campaign.scoped.mixin"

    distribution_group_id = fields.Many2one(
        "cc.mail.distribution.group", required=True, ondelete="restrict", index=True
    )
    membership_id = fields.Many2one(
        "cc.campaign.membership", required=True, ondelete="restrict", index=True
    )
    user_id = fields.Many2one(
        related="membership_id.user_id", store=True, readonly=True, index=True
    )
    state = fields.Selection(
        [
            ("pending_readback", "Pending Read-Back"),
            ("matched", "Read-Back Matched"),
            ("mismatch", "Mismatch"),
            ("revoked", "Revoked"),
        ],
        required=True,
        default="pending_readback",
        copy=False,
        index=True,
    )
    read_back_evidence_hash = fields.Char(size=64, readonly=True, copy=False)

    _group_membership_unique = models.Constraint(
        "unique(distribution_group_id, membership_id)",
        "A membership may appear only once in a distribution group.",
    )

    @api.model_create_multi
    def create(self, values_list):
        if any(values.get("state", "pending_readback") != "pending_readback" for values in values_list):
            raise AccessError(_("Distribution membership requires read-back."))
        return super().create(values_list)

    def write(self, values):
        if {
            "distribution_group_id",
            "membership_id",
            "campaign_id",
            "state",
            "read_back_evidence_hash",
        } & set(values) and self.env.context.get(
            "_cc_mail_distribution_capability"
        ) is not MAIL_DISTRIBUTION_WRITE_CAPABILITY:
            raise AccessError(_("Distribution membership is governed evidence."))
        return super().write(values)

    def unlink(self):
        raise AccessError(_("Distribution membership evidence cannot be deleted."))

    @api.constrains(
        "distribution_group_id", "membership_id", "campaign_id", "state"
    )
    def _check_membership(self):
        for record in self:
            group = record.distribution_group_id
            membership = record.membership_id
            if group.campaign_id != record.campaign_id:
                raise ValidationError(_("Distribution and membership scope differ."))
            if membership.campaign_id != record.campaign_id:
                raise ValidationError(_("A user cannot join another campaign distribution."))
            if membership.state != "active":
                raise ValidationError(_("Distribution requires an active membership."))
            if record.state == "matched" and group.state != "matched":
                raise ValidationError(_("The distribution group must match first."))

    def action_record_staging_readback(self, evidence_hash, matched=True):
        self.env["cc.mail.inbound.event"]._require_ingestion_service()
        if not SHA256_PATTERN.fullmatch((evidence_hash or "").lower()):
            raise ValidationError(_("Distribution read-back evidence must be SHA-256."))
        self.with_context(
            _cc_mail_distribution_capability=MAIL_DISTRIBUTION_WRITE_CAPABILITY
        ).write(
            {
                "state": "matched" if matched else "mismatch",
                "read_back_evidence_hash": evidence_hash.lower(),
            }
        )
        return True


class CcMailThread(models.Model):
    _name = "cc.mail.thread"
    _description = "Campaign-Owned Mail Thread"
    _inherit = ["cc.campaign.scoped.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "write_date desc, id desc"
    _rec_name = "subject"

    subject = fields.Char(required=True, tracking=True)
    campaign_code = fields.Char(required=True, readonly=True, index=True)
    route_id = fields.Many2one(
        "cc.mail.route", required=True, ondelete="restrict", index=True
    )
    recipient = fields.Char(required=True, readonly=True, index=True)
    external_sender_hash = fields.Char(required=True, size=64, readonly=True)
    thread_token_hash = fields.Char(required=True, size=64, readonly=True, index=True)
    state = fields.Selection(
        [("open", "Open"), ("waiting", "Waiting"), ("closed", "Closed")],
        required=True,
        default="open",
        tracking=True,
        index=True,
    )

    _thread_token_unique = models.Constraint(
        "unique(thread_token_hash)", "Campaign mail thread tokens must be unique."
    )

    @api.model_create_multi
    def create(self, values_list):
        prepared = []
        for original in values_list:
            values = dict(original)
            route = self.env["cc.mail.route"].browse(values.get("route_id")).exists()
            if not route or route.state != "testing":
                raise ValidationError(_("A staging-tested campaign route is required."))
            supplied_campaign = values.get("campaign_id")
            if supplied_campaign and supplied_campaign != route.campaign_id.id:
                raise AccessError(_("Mail campaign scope is derived from the route."))
            values["campaign_id"] = route.campaign_id.id
            supplied_code = values.get("campaign_code")
            if supplied_code and supplied_code != route.campaign_code:
                raise AccessError(_("Mail campaign code is derived from the route."))
            values["campaign_code"] = route.campaign_code
            if _normalized_address(values.get("recipient")) != route.address:
                raise ValidationError(_("Thread recipient must equal the campaign alias."))
            for field_name in ("external_sender_hash", "thread_token_hash"):
                if not SHA256_PATTERN.fullmatch((values.get(field_name) or "").lower()):
                    raise ValidationError(_("Mail identity hashes must be SHA-256."))
            prepared.append(values)
        return super().create(prepared)

    def write(self, values):
        if {
            "route_id",
            "campaign_id",
            "campaign_code",
            "recipient",
            "thread_token_hash",
        } & set(values):
            raise AccessError(_("Campaign mail thread ownership is immutable."))
        return super().write(values)

    def unlink(self):
        raise AccessError(_("Campaign mail thread evidence cannot be deleted."))

    def copy(self, default=None):
        raise AccessError(_("Campaign mail threads cannot be copied."))

    def prepare_outbound(self, idempotency_key, supplied_from=None):
        self.ensure_one()
        if not idempotency_key:
            raise ValidationError(_("Outbound mail requires an idempotency key."))
        identity = self.route_id.sender_identity_id
        if len(identity) != 1 or identity.state != "matched":
            raise ValidationError(_("The campaign sender identity has not matched."))
        supplied = _normalized_address(supplied_from or identity.from_address)
        if supplied != identity.from_address:
            raise ValidationError(_("The campaign From address cannot be overridden."))
        memberships = self.env["cc.mail.distribution.membership"].search(
            [
                ("distribution_group_id.route_id", "=", self.route_id.id),
                ("user_id", "=", self.env.user.id),
                ("state", "=", "matched"),
            ]
        )
        if not self.env.user.has_group(
            "codestra_cc_security.group_cc_global_administrator"
        ) and len(memberships) != 1:
            raise AccessError(_("Matched campaign distribution membership is required."))
        return {
            "schema_version": "1.0",
            "thread_id": self.id,
            "campaign_code": self.campaign_code,
            "route_address": self.route_id.address,
            "from": identity.from_address,
            "reply_to": identity.reply_to_address,
            "signature_html": identity.signature_html,
            "legal_footer_html": identity.legal_footer_html,
            "tracking_domain": identity.tracking_domain,
            "idempotency_key": idempotency_key,
            "external_send_enabled": False,
        }


class CcMailInboundEvent(models.Model):
    _name = "cc.mail.inbound.event"
    _description = "Immutable Campaign Mail Inbound Event"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "received_at desc, id desc"

    event_id = fields.Char(required=True, readonly=True, index=True)
    idempotency_key = fields.Char(required=True, readonly=True, index=True)
    correlation_id = fields.Char(required=True, readonly=True, index=True)
    message_id = fields.Char(required=True, readonly=True, index=True)
    route_id = fields.Many2one(
        "cc.mail.route", required=True, readonly=True, ondelete="restrict", index=True
    )
    thread_id = fields.Many2one(
        "cc.mail.thread", readonly=True, ondelete="restrict", index=True
    )
    state = fields.Selection(
        [("processed", "Processed"), ("quarantined", "Quarantined")],
        required=True,
        readonly=True,
        index=True,
    )
    event_type = fields.Char(required=True, readonly=True, index=True)
    payload_hash = fields.Char(required=True, size=64, readonly=True)
    received_at = fields.Datetime(required=True, readonly=True)

    _event_unique = models.Constraint(
        "unique(event_id)", "Campaign mail event IDs must be unique."
    )
    _idempotency_unique = models.Constraint(
        "unique(idempotency_key)", "Campaign mail idempotency keys must be unique."
    )
    _message_route_unique = models.Constraint(
        "unique(message_id, route_id)",
        "A message may have one effective result per campaign route.",
    )

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get(
            "_cc_mail_event_capability"
        ) is not MAIL_EVENT_WRITE_CAPABILITY:
            raise AccessError(_("Inbound mail events require the governed service."))
        return super().create(values_list)

    def write(self, values):
        if self.env.context.get(
            "_cc_mail_event_capability"
        ) is not MAIL_EVENT_WRITE_CAPABILITY:
            raise AccessError(_("Inbound mail events are immutable."))
        return super().write(values)

    def unlink(self):
        raise AccessError(_("Inbound mail event evidence cannot be deleted."))

    @api.model
    def _require_ingestion_service(self):
        if not self.env.su and not self.env.user.has_group(
            "codestra_cc_mail.group_cc_mail_ingestion_service"
        ):
            raise AccessError(_("Campaign mail ingestion-service permission is required."))

    @api.model
    def _event_values(self, payload, route, payload_hash, state, thread=False):
        return {
            "event_id": payload["event_id"],
            "idempotency_key": payload["idempotency_key"],
            "correlation_id": payload["correlation_id"],
            "message_id": payload["message_id"],
            "route_id": route.id,
            "thread_id": thread.id if thread else False,
            "campaign_id": route.campaign_id.id,
            "state": state,
            "event_type": (
                "cc.email.received.v1"
                if state == "processed"
                else "cc.email.quarantined.v1"
            ),
            "payload_hash": payload_hash,
            "received_at": fields.Datetime.to_datetime(payload["occurred_at"]),
        }

    @api.model
    def _quarantine(self, payload, route, payload_hash, reason, metadata=None):
        event = self.with_context(
            _cc_mail_event_capability=MAIL_EVENT_WRITE_CAPABILITY
        ).create(self._event_values(payload, route, payload_hash, "quarantined"))
        self.env["cc.mail.quarantine"].with_context(
            _cc_mail_quarantine_capability=MAIL_QUARANTINE_WRITE_CAPABILITY
        ).create(
            {
                "campaign_id": route.campaign_id.id,
                "route_id": route.id,
                "event_id": event.id,
                "reason": reason,
                "payload_hash": payload_hash,
                "thread_token_hash": _sha256(payload.get("thread_token") or ""),
                "metadata_json": metadata or {},
            }
        )
        return event

    @api.model
    def ingest_staging_event(self, payload):
        self._require_ingestion_service()
        required = {
            "event_id",
            "idempotency_key",
            "correlation_id",
            "occurred_at",
            "message_id",
            "recipient",
            "sender",
            "subject",
            "integrity_hash",
        }
        missing = sorted(required.difference(payload or {}))
        if missing:
            raise ValidationError(_("Missing campaign mail fields: %s") % ", ".join(missing))
        if not SHA256_PATTERN.fullmatch(str(payload["integrity_hash"]).lower()):
            raise ValidationError(_("The verified integrity envelope hash is invalid."))
        occurred_at = fields.Datetime.to_datetime(payload["occurred_at"])
        if not occurred_at or abs(
            (fields.Datetime.now() - occurred_at).total_seconds()
        ) > 300:
            raise ValidationError(_("Inbound mail is outside the replay window."))
        if self.search_count(
            [
                "|",
                ("event_id", "=", payload["event_id"]),
                ("idempotency_key", "=", payload["idempotency_key"]),
            ]
        ):
            raise ValidationError(_("Replayed campaign mail event rejected."))
        recipient = _normalized_address(payload["recipient"])
        sender = _normalized_address(payload["sender"])
        if not recipient or not sender:
            raise ValidationError(_("Inbound sender and recipient must be valid addresses."))
        route = self.env["cc.mail.route"].search(
            [("address", "=", recipient)], limit=2
        )
        if len(route) != 1:
            raise ValidationError(_("Recipient must resolve to exactly one campaign route."))
        if route.state != "testing" or route.direction not in {"inbound", "both"}:
            raise ValidationError(_("The campaign route is not open for staging ingestion."))
        if route.campaign_id.environment == "production":
            raise AccessError(_("Production inbound email mutation remains disabled."))
        metadata = {
            key: value
            for key, value in payload.items()
            if key not in {"body_html", "body_text", "attachments", "sender"}
        }
        metadata["sender_hash"] = _sha256(sender)
        metadata["attachment_hashes"] = [
            _sha256(item.get("content_base64") or "")
            for item in payload.get("attachments") or []
        ]
        payload_hash = _sha256(_canonical_json(metadata))
        if int(payload.get("raw_size") or 0) > MAX_MESSAGE_BYTES:
            return self._quarantine(
                payload, route, payload_hash, "MESSAGE_SIZE_EXCEEDED"
            )

        thread_token = payload.get("thread_token") or payload["message_id"]
        thread_token_hash = _sha256(thread_token)
        thread = self.env["cc.mail.thread"].search(
            [("thread_token_hash", "=", thread_token_hash)], limit=1
        )
        if thread and thread.route_id != route:
            return self._quarantine(
                payload,
                route,
                payload_hash,
                "THREAD_CAMPAIGN_MISMATCH",
                {"existing_thread_campaign_hash": _sha256(thread.campaign_id.workspace_uuid)},
            )
        if not thread:
            thread = self.env["cc.mail.thread"].with_context(
                mail_create_nosubscribe=True,
                mail_create_nolog=True,
                mail_post_autofollow=False,
            ).create(
                {
                    "subject": payload["subject"] or _("No Subject"),
                    "route_id": route.id,
                    "campaign_id": route.campaign_id.id,
                    "recipient": route.address,
                    "external_sender_hash": _sha256(sender),
                    "thread_token_hash": thread_token_hash,
                }
            )

        attachment_ids = []
        for item in payload.get("attachments") or []:
            filename = (item.get("filename") or "attachment").strip()
            mimetype = (item.get("mimetype") or "application/octet-stream").lower()
            try:
                content = base64.b64decode(
                    item.get("content_base64") or "", validate=True
                )
            except Exception as error:
                raise ValidationError(_("Attachment encoding is invalid.")) from error
            extension = (
                "." + filename.rsplit(".", 1)[-1].lower()
                if "." in filename
                else ""
            )
            evidence_hash = str(item.get("scan_evidence_hash") or "").lower()
            clean = (
                len(content) <= MAX_ATTACHMENT_BYTES
                and extension not in PROHIBITED_EXTENSIONS
                and mimetype.startswith(SAFE_MIME_PREFIXES)
                and item.get("scan_status") == "clean"
                and SHA256_PATTERN.fullmatch(evidence_hash)
            )
            if not clean:
                self.env["cc.mail.quarantine"].with_context(
                    _cc_mail_quarantine_capability=MAIL_QUARANTINE_WRITE_CAPABILITY
                ).create(
                    {
                        "campaign_id": route.campaign_id.id,
                        "route_id": route.id,
                        "reason": "ATTACHMENT_POLICY_REJECTED",
                        "payload_hash": _sha256(content),
                        "thread_token_hash": thread_token_hash,
                        "metadata_json": {
                            "filename_hash": _sha256(filename),
                            "size": len(content),
                            "mimetype": mimetype,
                        },
                    }
                )
                continue
            attachment = self.env["ir.attachment"].create(
                {
                    "name": filename,
                    "datas": base64.b64encode(content),
                    "mimetype": mimetype,
                    "res_model": thread._name,
                    "res_id": thread.id,
                    "cc_scan_state": "clean",
                    "cc_scan_evidence_hash": evidence_hash,
                    "cc_content_hash": _sha256(content),
                }
            )
            attachment_ids.append(attachment.id)
        body = html_sanitize(
            payload.get("body_html") or payload.get("body_text") or "",
            sanitize_tags=True,
            sanitize_attributes=True,
        )
        thread.with_context(
            mail_create_nosubscribe=True, mail_post_autofollow=False
        ).message_post(
            # html_sanitize above is the single trust transition for message HTML.
            body=Markup(body),  # nosec B704
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
            email_from=sender,
            attachment_ids=attachment_ids,
        )
        return self.with_context(
            _cc_mail_event_capability=MAIL_EVENT_WRITE_CAPABILITY
        ).create(self._event_values(payload, route, payload_hash, "processed", thread))


class CcMailQuarantine(models.Model):
    _name = "cc.mail.quarantine"
    _description = "Immutable Campaign Mail Quarantine Evidence"
    _inherit = "cc.campaign.scoped.mixin"
    _order = "create_date desc, id desc"

    route_id = fields.Many2one(
        "cc.mail.route", required=True, readonly=True, ondelete="restrict", index=True
    )
    event_id = fields.Many2one(
        "cc.mail.inbound.event", readonly=True, ondelete="restrict", index=True
    )
    reason = fields.Selection(
        [
            ("THREAD_CAMPAIGN_MISMATCH", "Thread/Campaign Mismatch"),
            ("ATTACHMENT_POLICY_REJECTED", "Attachment Policy Rejected"),
            ("MESSAGE_SIZE_EXCEEDED", "Message Size Exceeded"),
        ],
        required=True,
        readonly=True,
        index=True,
    )
    payload_hash = fields.Char(required=True, size=64, readonly=True)
    thread_token_hash = fields.Char(required=True, size=64, readonly=True)
    metadata_json = fields.Json(required=True, default=dict, readonly=True)

    @api.model_create_multi
    def create(self, values_list):
        if self.env.context.get(
            "_cc_mail_quarantine_capability"
        ) is not MAIL_QUARANTINE_WRITE_CAPABILITY:
            raise AccessError(_("Quarantine evidence requires the governed producer."))
        return super().create(values_list)

    def write(self, values):
        raise AccessError(_("Campaign mail quarantine evidence is immutable."))

    def unlink(self):
        raise AccessError(_("Campaign mail quarantine evidence cannot be deleted."))

    @api.constrains(
        "route_id", "campaign_id", "event_id", "payload_hash", "thread_token_hash"
    )
    def _check_quarantine(self):
        for record in self:
            if record.route_id.campaign_id != record.campaign_id:
                raise ValidationError(_("Quarantine route and campaign differ."))
            if record.event_id and record.event_id.campaign_id != record.campaign_id:
                raise ValidationError(_("Quarantine event and campaign differ."))
            for value in (record.payload_hash, record.thread_token_hash):
                if not SHA256_PATTERN.fullmatch(value or ""):
                    raise ValidationError(_("Quarantine identifiers must be SHA-256."))


class MailMessage(models.Model):
    _inherit = "mail.message"

    cc_campaign_id = fields.Many2one(
        "cc.campaign", readonly=True, ondelete="restrict", index=True
    )

    @api.model_create_multi
    def create(self, values_list):
        prepared = [
            _tag_create_values(self.env, values, "model", "res_id")
            for values in values_list
        ]
        return super().create(prepared)

    def write(self, values):
        if len(self) > 1 and {"model", "res_id"} & set(values):
            for record in self:
                record.write(values)
            return True
        prepared = (
            _prepare_binding_write(self, values, "model", "res_id")
            if self
            else values
        )
        return super().write(prepared)


class MailFollowers(models.Model):
    _inherit = "mail.followers"

    cc_campaign_id = fields.Many2one(
        "cc.campaign", readonly=True, ondelete="restrict", index=True
    )

    @api.model_create_multi
    def create(self, values_list):
        prepared = [
            _tag_create_values(self.env, values, "res_model", "res_id")
            for values in values_list
        ]
        records = super().create(prepared)
        records._check_internal_follower_campaign()
        return records

    def write(self, values):
        if len(self) > 1 and {"res_model", "res_id"} & set(values):
            for record in self:
                record.write(values)
            return True
        prepared = (
            _prepare_binding_write(self, values, "res_model", "res_id")
            if self
            else values
        )
        result = super().write(prepared)
        self._check_internal_follower_campaign()
        return result

    def _check_internal_follower_campaign(self):
        for follower in self.filtered(
            lambda item: item.cc_campaign_id and item.res_model == "cc.mail.thread"
        ):
            internal_users = follower.partner_id.user_ids.filtered(
                lambda user: user.has_group("base.group_user")
            )
            for user in internal_users:
                if user.has_group(
                    "codestra_cc_security.group_cc_global_administrator"
                ) or user.has_group("codestra_cc_security.group_cc_auditor"):
                    continue
                memberships = user.cc_campaign_membership_ids.filtered(
                    lambda item: item.state == "active"
                    and item.campaign_id == follower.cc_campaign_id
                )
                if not memberships:
                    raise ValidationError(
                        _("Internal chatter followers must belong to the same campaign.")
                    )


class MailActivity(models.Model):
    _inherit = "mail.activity"

    cc_campaign_id = fields.Many2one(
        "cc.campaign", readonly=True, ondelete="restrict", index=True
    )

    @api.model_create_multi
    def create(self, values_list):
        prepared = []
        for original in values_list:
            values = dict(original)
            model_name = values.get("res_model")
            if not model_name and values.get("res_model_id"):
                model_name = self.env["ir.model"].browse(
                    values["res_model_id"]
                ).model
            campaign = _resource_campaign(self.env, model_name, values.get("res_id"))
            supplied = values.get("cc_campaign_id")
            if campaign:
                if supplied and supplied != campaign.id:
                    raise AccessError(
                        _("Campaign tags are derived from the linked resource.")
                    )
                values["cc_campaign_id"] = campaign.id
            elif supplied:
                raise AccessError(
                    _("A campaign tag cannot be supplied without a scoped resource.")
                )
            prepared.append(values)
        return super().create(prepared)

    def write(self, values):
        if "cc_campaign_id" in values:
            raise AccessError(_("Activity campaign scope is immutable."))
        return super().write(values)


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    cc_campaign_id = fields.Many2one(
        "cc.campaign", readonly=True, ondelete="restrict", index=True
    )
    cc_scan_state = fields.Selection(
        [
            ("not_required", "Not Campaign Scoped"),
            ("pending", "Pending Scan"),
            ("clean", "Clean"),
            ("quarantined", "Quarantined"),
        ],
        required=True,
        default="not_required",
        readonly=True,
        index=True,
    )
    cc_scan_evidence_hash = fields.Char(size=64, readonly=True)
    cc_content_hash = fields.Char(size=64, readonly=True)

    @api.model_create_multi
    def create(self, values_list):
        prepared = []
        for original in values_list:
            values = _tag_create_values(self.env, original, "res_model", "res_id")
            if values.get("cc_campaign_id"):
                values.setdefault("cc_scan_state", "pending")
                if values.get("cc_scan_state") == "clean":
                    allowed_clean = self.env.user.has_group(
                        "codestra_cc_mail.group_cc_mail_ingestion_service"
                    ) or self.env.user.has_group(
                        "codestra_cc_security.group_cc_global_administrator"
                    )
                    if not allowed_clean:
                        raise AccessError(
                            _("Only the governed scanner service may mark content clean.")
                        )
                    for field_name in ("cc_scan_evidence_hash", "cc_content_hash"):
                        if not SHA256_PATTERN.fullmatch(
                            (values.get(field_name) or "").lower()
                        ):
                            raise ValidationError(
                                _("Clean campaign attachments require SHA-256 evidence.")
                            )
            elif values.get("cc_scan_state", "not_required") != "not_required":
                raise ValidationError(_("Only campaign attachments use scan state."))
            prepared.append(values)
        return super().create(prepared)

    def write(self, values):
        protected = {
            "cc_campaign_id",
            "cc_scan_state",
            "cc_scan_evidence_hash",
            "cc_content_hash",
        }
        if protected & set(values):
            raise AccessError(_("Campaign attachment evidence is immutable."))
        if len(self) > 1 and {"res_model", "res_id"} & set(values):
            for record in self:
                record.write(values)
            return True
        prepared = (
            _prepare_binding_write(self, values, "res_model", "res_id")
            if self
            else values
        )
        if prepared.get("cc_campaign_id"):
            prepared.setdefault("cc_scan_state", "pending")
        return super().write(prepared)
