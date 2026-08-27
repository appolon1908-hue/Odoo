import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError


def normalize_phone(value):
    value = str(value or "").strip()
    if not value:
        return False
    if re.search(r"[^0-9+().\-\s]", value):
        raise ValidationError("Telephone number contains unsupported characters.")
    if "+" in value and (not value.startswith("+") or value.count("+") != 1):
        raise ValidationError("The plus sign is permitted only once at the beginning.")
    digits = re.sub(r"\D", "", value)
    if value.startswith("+"):
        if 8 <= len(digits) <= 15:
            return "+" + digits
        raise ValidationError("E.164 numbers must contain between 8 and 15 digits.")
    if value.startswith("00"):
        international = digits[2:]
        if 8 <= len(international) <= 15:
            return "+" + international
        raise ValidationError("International numbers must contain between 8 and 15 digits.")
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    raise ValidationError("Telephone number cannot be normalized safely.")


class ResPartner(models.Model):
    _inherit = "res.partner"

    x_codestra_phone_e164 = fields.Char(compute="_compute_codestra_phone", store=True, index=True)

    @api.depends("phone")
    def _compute_codestra_phone(self):
        for record in self:
            try:
                record.x_codestra_phone_e164 = normalize_phone(record.phone)
            except ValidationError:
                record.x_codestra_phone_e164 = False
