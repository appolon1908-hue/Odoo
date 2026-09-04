from .outbox import EVENT_TYPE as DESIGN_REQUEST_EVENT
from .outbox import SCHEMA_VERSION, canonical_json

APPROVAL_EVENT = "campaign.approved.v1"
DESIGN_MANIFEST_SCHEMA = "campaign-provisioning.v1"
AUTOMATIC_STATE_CAPABILITY = object()
REVISION_STATE_CAPABILITY = object()
APPROVED_BUSINESS_UNITS = {
    "MOY",
    "COD",
    "SCP",
    "MBL",
    "RLP",
    "FTP",
    "TRX",
    "CAL",
    "TEST",
    "STAGING",
}
LIST_ID_RANGES = {
    "MOY": (11000, 11999),
    "COD": (21000, 21999),
    "SCP": (31000, 31999),
    "MBL": (41000, 41999),
    "RLP": (51000, 51999),
    "FTP": (61000, 61999),
    "TRX": (71000, 71999),
    "CAL": (81000, 81999),
    "TEST": (91000, 91999),
    "STAGING": (91000, 91999),
}
ENVIRONMENT_SCOPE_CODES = {
    "test": "TEST",
    "staging": "STAGING",
    "production": "PROD",
}
DIRECTION_CODES = {
    "inbound": "IN",
    "outbound": "OUT",
    "blended": "BLENDED",
}
REQUIRED_MANIFEST_POLICY_KEYS = {
    "calling_hours",
    "time_zone",
    "consent_policy",
    "dnc_policy",
    "recording_policy",
    "transfer_policy",
}
REQUIRED_DESIGN_INPUT_KEYS = {
    "default_language",
    "recording_policy",
    "default_lead_source_policy",
    "agent_roles",
    "transfer_roles",
    "callback_policy",
    "appointment_policy",
    "disposition_family",
    "script_template",
    "n8n_automation_template",
    "reporting_category",
    "activation_policy",
}
SECRET_KEY_PARTS = {
    "password",
    "passwd",
    "token",
    "secret",
    "credential",
    "private_key",
    "sip_password",
}
DESIGN_REVISION_STATES = [
    ("requested", "Requested"),
    ("hash_only", "Hash Only"),
    ("ready", "Ready for Approval"),
    ("approved", "Approved"),
    ("superseded", "Superseded"),
    ("rejected", "Rejected"),
]


def normalized_hash(value):
    return str(value or "").removeprefix("sha256:").lower()


def contains_secret_key(value):
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if any(part in normalized for part in SECRET_KEY_PARTS):
                return True
            if contains_secret_key(child):
                return True
    elif isinstance(value, list):
        return any(contains_secret_key(item) for item in value)
    return False
