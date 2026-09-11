from odoo import api, fields, models
from odoo.exceptions import ValidationError


class VicidialAgentWebRTC(models.Model):
    _inherit = "codestra.vicidial.agent"

    webrtc_enabled = fields.Boolean(
        string="WebRTC enabled",
        default=False,
        help=(
            "Allow this agent to use a browser WebRTC phone. "
            "The agent may have at most one assigned phone extension."
        ),
    )
    phone_ids = fields.One2many(
        "codestra.vicidial.phone",
        "assigned_agent_id",
        string="Assigned phone",
        help="At most one phone extension may be assigned to an agent.",
    )

    @api.constrains("webrtc_enabled", "phone_login")
    def _check_webrtc_phone_binding(self):
        Phone = self.env["codestra.vicidial.phone"]
        for agent in self:
            phones = Phone.search(
                [
                    ("assigned_agent_id", "=", agent.id),
                    ("active", "=", True),
                    ("is_webrtc", "=", True),
                ]
            )
            for phone in phones:
                if not agent.webrtc_enabled:
                    raise ValidationError(
                        "Disable or unassign the active WebRTC phone before disabling WebRTC "
                        "for this agent."
                    )
                if agent.phone_login and phone.extension != agent.phone_login:
                    raise ValidationError(
                        "The agent phone login must match the assigned WebRTC extension."
                    )


class VicidialPhoneWebRTC(models.Model):
    _inherit = "codestra.vicidial.phone"

    is_webrtc = fields.Boolean(
        string="WebRTC phone",
        default=False,
        help="Mark this endpoint as a browser WebRTC phone.",
    )

    _assigned_agent_unique = models.Constraint(
        "UNIQUE(assigned_agent_id)",
        "An agent may have only one assigned phone extension.",
    )
    _extension_unique = models.Constraint(
        "UNIQUE(extension)",
        "A phone extension may be assigned only once.",
    )

    @api.constrains("assigned_agent_id", "is_webrtc", "active", "extension")
    def _check_assignment(self):
        for phone in self:
            agent = phone.assigned_agent_id
            if not agent or not phone.active:
                continue
            if agent.webrtc_enabled != phone.is_webrtc:
                raise ValidationError(
                    "The agent WebRTC option and assigned phone type must match."
                )
            if phone.is_webrtc and agent.phone_login and phone.extension != agent.phone_login:
                raise ValidationError(
                    "The assigned WebRTC extension must match the agent phone login."
                )


class ResUsersWebRTC(models.Model):
    _inherit = "res.users"

    webrtc_enabled = fields.Boolean(
        string="WebRTC calling enabled",
        related="vicidial_agent_id.webrtc_enabled",
        readonly=False,
        help="Convenience setting for the linked VICIdial agent.",
    )
