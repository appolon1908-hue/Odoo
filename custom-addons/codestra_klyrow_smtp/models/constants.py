import os

from odoo.tools import email_domain_extract, email_normalize


SHARED_KLYROW_DOMAINS = (
    "breero.com",
    "breero.shop",
    "codestra.agency",
    "codestra.cloud",
    "codestra.co",
    "codestra.digital",
    "codestra.media",
    "klyrow.com",
    "kyqra.com",
    "moneybee.loan",
    "moneybeeloan.com",
    "nativoenglish.com",
    "telnexa.co",
)
BEYVRA_DOMAIN = "beyvra.com"
MANAGED_DOMAINS = frozenset((*SHARED_KLYROW_DOMAINS, BEYVRA_DOMAIN))
EXCLUDED_DOMAINS = frozenset({"booked4seasons.com"})
CURRENT_SIGNED_INBOUND_DOMAINS = frozenset({"codestra.co", "klyrow.com"})
CANONICAL_TRACKING_HOST = "track.klyrow.com"
LIVE_DELIVERY_PARAMETER = "codestra.mail.live_delivery_enabled"
LIVE_DELIVERY_ENVIRONMENT_SWITCHES = (
    "ENABLE_EXTERNAL_DELIVERY",
    "EMAIL_DELIVERY",
    "LIVE_EMAIL_DELIVERY",
)
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def switch_enabled(name):
    return (os.environ.get(name) or "").strip().lower() in _TRUE_VALUES


def domain_from_address(address):
    normalized = email_normalize(address or "")
    return email_domain_extract(normalized) if normalized else False


def true_values():
    return _TRUE_VALUES
