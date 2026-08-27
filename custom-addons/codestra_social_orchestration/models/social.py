from odoo import fields, models


class SocialCampaign(models.Model):
    _name = "codestra.social.campaign"
    _description = "Codestra Social Campaign"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(required=True, tracking=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)
    post_ids = fields.One2many("codestra.social.post", "campaign_id")
    active = fields.Boolean(default=True)


class SocialChannel(models.Model):
    _name = "codestra.social.channel"
    _description = "Codestra Social Channel"

    name = fields.Char(required=True)
    platform = fields.Char(required=True)
    postiz_integration_id = fields.Char(index=True, copy=False)
    owner_approved = fields.Boolean(default=False)
    disabled = fields.Boolean(default=False)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)


class SocialMedia(models.Model):
    _name = "codestra.social.media"
    _description = "Codestra Social Media Reference"

    name = fields.Char(required=True)
    checksum = fields.Char(required=True, copy=False)
    media_type = fields.Selection([("image", "Image"), ("video", "Video")], required=True)
    postiz_media_id = fields.Char(copy=False)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True)


class SocialPost(models.Model):
    _name = "codestra.social.post"
    _description = "Codestra Social Post"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    _STATES = [
        ("draft", "Draft"), ("pending_approval", "Pending Approval"),
        ("approved", "Approved"), ("queued", "Queued"),
        ("scheduled", "Scheduled"), ("published", "Published"),
        ("failed_retryable", "Failed Retryable"), ("failed_final", "Failed Final"),
        ("human_review", "Human Review"), ("cancelled", "Cancelled"),
    ]
    name = fields.Char(required=True, tracking=True)
    campaign_id = fields.Many2one("codestra.social.campaign", required=True, ondelete="restrict")
    company_id = fields.Many2one(related="campaign_id.company_id", store=True, index=True)
    content = fields.Text(required=True)
    state = fields.Selection(_STATES, default="draft", required=True, tracking=True)
    channel_ids = fields.Many2many("codestra.social.channel")
    media_ids = fields.Many2many("codestra.social.media")
    scheduled_at = fields.Datetime()
    approval_user_id = fields.Many2one("res.users", copy=False)
    approval_hash = fields.Char(copy=False)
    middleware_command_id = fields.Char(copy=False, index=True)
    postiz_post_id = fields.Char(copy=False, index=True)
    publication_ids = fields.One2many("codestra.social.publication", "post_id")
    failure_ids = fields.One2many("codestra.social.failure", "post_id")
    trace_id = fields.Char(copy=False, index=True)
    correlation_id = fields.Char(copy=False, index=True)


class SocialApproval(models.Model):
    _name = "codestra.social.approval"
    _description = "Codestra Social Approval"

    post_id = fields.Many2one("codestra.social.post", required=True, ondelete="restrict")
    user_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user)
    decision = fields.Selection([("approved", "Approved"), ("rejected", "Rejected")], required=True)
    content_hash = fields.Char(required=True, copy=False)
    note = fields.Text()


class SocialPublication(models.Model):
    _name = "codestra.social.publication"
    _description = "Codestra Social Publication"

    post_id = fields.Many2one("codestra.social.post", required=True, ondelete="restrict")
    channel_id = fields.Many2one("codestra.social.channel", required=True, ondelete="restrict")
    state = fields.Selection([("queued", "Queued"), ("scheduled", "Scheduled"), ("published", "Published"), ("failed", "Failed")], required=True, default="queued")
    postiz_post_id = fields.Char(copy=False)
    published_at = fields.Datetime()
    error_message = fields.Text()


class SocialAnalytics(models.Model):
    _name = "codestra.social.analytics"
    _description = "Codestra Social Analytics"

    post_id = fields.Many2one("codestra.social.post", ondelete="restrict")
    channel_id = fields.Many2one("codestra.social.channel", ondelete="restrict")
    period = fields.Date(required=True)
    summary = fields.Json(default=dict)
    trace_id = fields.Char(copy=False)


class SocialFailure(models.Model):
    _name = "codestra.social.failure"
    _description = "Codestra Social Failure"

    post_id = fields.Many2one("codestra.social.post", required=True, ondelete="restrict")
    retryable = fields.Boolean(default=False)
    error_code = fields.Char(required=True)
    message = fields.Text(required=True)
    resolved = fields.Boolean(default=False)
