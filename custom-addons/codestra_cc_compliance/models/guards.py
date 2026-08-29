import re

from odoo import _, api, models
from odoo.exceptions import ValidationError


CARD_CANDIDATE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
SECRET_LABEL = re.compile(
    r"(?i)\b(?:cvv|cvc|security\s*code|password|passcode|api\s*key|"
    r"authentication\s*secret|bearer\s*token|bank\s*account|routing\s*number|iban)"
    r"\s*[:=]\s*[a-z0-9][a-z0-9 ._/-]{2,}"
)


def _luhn(number):
    digits = [int(character) for character in number]
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def contains_prohibited_payment_data(value):
    text = str(value or "")
    if SECRET_LABEL.search(text):
        return True
    for match in CARD_CANDIDATE.finditer(text):
        digits = "".join(character for character in match.group(0) if character.isdigit())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            return True
    return False


def validate_safe_text(values):
    if any(contains_prohibited_payment_data(value) for value in values if value):
        raise ValidationError(
            _(
                "Payment-card data, security codes, bank credentials, and authentication "
                "secrets are prohibited. Use the governed tokenized payment workflow."
            )
        )


class CrmLead(models.Model):
    _inherit = "crm.lead"

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            validate_safe_text(
                values.get(field_name)
                for field_name in ("description", "do_not_contact_reason")
            )
        return super().create(values_list)

    def write(self, values):
        validate_safe_text(
            values.get(field_name)
            for field_name in ("description", "do_not_contact_reason")
        )
        return super().write(values)


class CampaignNote(models.Model):
    _inherit = "codestra.campaign.note"

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            validate_safe_text([values.get("body")])
        return super().create(values_list)

    def write(self, values):
        validate_safe_text([values.get("body")])
        return super().write(values)


class MailMessage(models.Model):
    _inherit = "mail.message"

    @staticmethod
    def _is_contact_center_model(model_name):
        return model_name == "crm.lead" or str(model_name or "").startswith(
            ("cc.", "call.center.", "codestra.")
        )

    @api.model_create_multi
    def create(self, values_list):
        for values in values_list:
            if self._is_contact_center_model(values.get("model")):
                validate_safe_text([values.get("subject"), values.get("body")])
        return super().create(values_list)

    def write(self, values):
        if {"subject", "body"}.intersection(values):
            for message in self:
                if self._is_contact_center_model(message.model):
                    validate_safe_text([values.get("subject"), values.get("body")])
        return super().write(values)
