from odoo import api, fields, models
from odoo.exceptions import ValidationError


class IntegrationMapping(models.Model):
    _inherit = "codestra.integration.mapping"

    namespace = fields.Char(default="default", required=True, index=True)
    destination_system = fields.Char(required=True, index=True)
    source_key = fields.Char(required=True, index=True)
    destination_key = fields.Char(required=True)
    mapping_value = fields.Text()
    priority = fields.Integer(default=100)
    valid_from = fields.Datetime()
    valid_to = fields.Datetime()
    notes = fields.Text()

    @api.constrains("mapping_value")
    def _reject_executable_mapping(self):
        forbidden = ("{{", "{%", "eval(", "exec(", "import os", "select ", "insert ", "#!/")
        for record in self:
            if any(item in (record.mapping_value or "").lower() for item in forbidden):
                raise ValidationError("Executable templates, code, SQL, and shell content are prohibited.")

    _active_mapping_unique = models.Constraint(
        "UNIQUE(namespace, source_system, destination_system, source_key, active)",
        "An active mapping already exists for this source and destination key.",
    )
