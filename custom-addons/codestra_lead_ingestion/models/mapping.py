from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


TARGETS = [
    ("first_name", "First Name"), ("last_name", "Last Name"),
    ("phone", "Primary Phone"), ("alternative_phone", "Alternative Phone"),
    ("email", "Email"), ("external_reference", "External Reference"),
    ("country", "Country"), ("timezone", "Timezone"),
    ("campaign", "Campaign"), ("source", "Source"),
    ("voice_consent", "Voice Consent"), ("sms_consent", "SMS Consent"),
    ("whatsapp_consent", "WhatsApp Consent"),
    ("consent_timestamp", "Consent Timestamp"),
    ("consent_source", "Consent Source"),
    ("custom_script_field", "Custom Script Field"),
]


class LeadColumnMapping(models.Model):
    _name = "codestra.lead.column.mapping"
    _description = "Lead Column Mapping"
    _order = "name"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda s: s.env.company)
    campaign_id = fields.Many2one("call.center.campaign")
    schema_version = fields.Char(default="1.0", required=True)
    line_ids = fields.One2many("codestra.lead.column.mapping.line", "mapping_id", copy=True)
    notes = fields.Text()

    @api.constrains("line_ids")
    def _check_required_targets(self):
        for mapping in self:
            targets = mapping.line_ids.mapped("target_field")
            if mapping.line_ids and "phone" not in targets:
                raise ValidationError(_("A mapping requires a primary phone column."))
            if len(targets) != len(set(targets)):
                raise ValidationError(_("A target field may be mapped only once."))


class LeadColumnMappingLine(models.Model):
    _name = "codestra.lead.column.mapping.line"
    _description = "Lead Column Mapping Line"
    _order = "sequence, id"

    mapping_id = fields.Many2one("codestra.lead.column.mapping", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    source_column = fields.Char(required=True)
    target_field = fields.Selection(TARGETS, required=True)
    required = fields.Boolean()
    default_value = fields.Char()
    custom_key = fields.Char(help="Allowlisted key for custom script fields; never executable code.")

    @api.constrains("source_column", "custom_key")
    def _check_safe_names(self):
        for line in self:
            for value in (line.source_column, line.custom_key):
                if value and any(token in value for token in ("__", "import ", "eval(", "exec(", ";")):
                    raise ValidationError(_("Mapping values cannot contain executable expressions."))
