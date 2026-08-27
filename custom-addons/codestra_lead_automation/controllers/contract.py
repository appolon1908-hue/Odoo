from __future__ import annotations

import json
import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

ACTIONS = {
    "CREATE_LEAD",
    "UPDATE_ALLOWLISTED_FIELDS",
    "ASSIGN_AUTHORIZED_TEAM",
    "ASSIGN_AUTHORIZED_USER",
    "CHANGE_AUTHORIZED_STAGE",
    "CREATE_INTERNAL_CALLBACK_ACTIVITY",
}
ACK_RESULTS = {
    "APPLIED",
    "NO_CHANGE",
    "DENIED",
    "CONSENT_BLOCKED",
    "DNC_BLOCKED",
    "QUARANTINED",
    "FAILED",
}
REQUIRED = {
    "contract_version",
    "automation_event_id",
    "idempotency_key",
    "environment",
    "company_key",
    "business_unit_key",
    "campaign_key",
    "automation_action",
    "policy_version",
    "correlation_id",
    "attributes_schema_key",
    "attributes",
    "consent_snapshot",
    "workflow_execution_id",
    "result_code",
}
OPTIONAL = {"lead_uid", "source_reference"}


class ContractError(ValueError):
    pass


def _text(value: Any, label: str, maximum: int, prefix: str = "") -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ContractError(f"invalid {label}")
    if prefix and not value.startswith(prefix):
        raise ContractError(f"invalid {label}")
    return value


@lru_cache(maxsize=8)
def _attribute_schema(key: str) -> dict[str, Any]:
    path = Path(__file__).resolve().parents[1] / "schemas" / "lead-automation" / f"{key}.json"
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError("unknown attributes schema") from exc
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise ContractError("attribute schema is not fail closed")
    return schema


def _validate_attributes(key: str, value: Any) -> None:
    schema = _attribute_schema(key)
    if not isinstance(value, dict) or len(value) > schema["maxProperties"]:
        raise ContractError("invalid attributes")
    properties = schema["properties"]
    if set(value) - set(properties):
        raise ContractError("attribute outside allowlist")
    for name, item in value.items():
        rule = properties[name]
        if "enum" in rule and item not in rule["enum"]:
            raise ContractError(f"invalid attribute {name}")
        if rule.get("type") == "boolean" and type(item) is not bool:
            raise ContractError(f"invalid attribute {name}")
        if rule.get("type") == "string" and (
            not isinstance(item, str) or not re.fullmatch(rule["pattern"], item)
        ):
            raise ContractError(f"invalid attribute {name}")


def validate_apply(body: Mapping[str, Any]) -> None:
    keys = set(body)
    if not REQUIRED <= keys or keys - REQUIRED - OPTIONAL:
        raise ContractError("apply fields do not match contract")
    if body["contract_version"] != "1.1" or body["automation_action"] not in ACTIONS:
        raise ContractError("invalid contract or action")
    if body["environment"] not in {"test", "staging", "production"}:
        raise ContractError("invalid environment")
    _text(body["automation_event_id"], "automation_event_id", 68, "LAE-")
    idem = _text(body["idempotency_key"], "idempotency_key", 64)
    if not re.fullmatch(r"[A-Fa-f0-9]{64}", idem):
        raise ContractError("invalid idempotency key")
    for field, maximum in (
        ("company_key", 18),
        ("business_unit_key", 63),
        ("campaign_key", 64),
        ("policy_version", 32),
        ("result_code", 48),
    ):
        _text(body[field], field, maximum)
    if not re.fullmatch(r"COMPANY-[1-9][0-9]{0,9}", body["company_key"]):
        raise ContractError("invalid company key")
    try:
        UUID(str(body["correlation_id"]))
    except ValueError as exc:
        raise ContractError("invalid correlation id") from exc
    _text(body["workflow_execution_id"], "workflow_execution_id", 68, "N8N-")
    if "lead_uid" in body:
        _text(body["lead_uid"], "lead_uid", 69, "LEAD-")
    if "source_reference" in body:
        _text(body["source_reference"], "source_reference", 68, "SRC-")
    _validate_attributes(body["attributes_schema_key"], body["attributes"])
    consent = body["consent_snapshot"]
    consent_fields = {
        "consent_status",
        "consent_purpose",
        "consent_source",
        "consent_updated_at",
        "dnc_status",
        "dnc_updated_at",
        "jurisdiction",
        "source_system",
    }
    if not isinstance(consent, dict) or set(consent) != consent_fields:
        raise ContractError("invalid consent snapshot")
    if consent["consent_status"] not in {"granted", "denied", "expired", "unknown"}:
        raise ContractError("invalid consent status")
    if type(consent["dnc_status"]) is not bool or consent["source_system"] != "odoo":
        raise ContractError("invalid DNC snapshot")


def validate_ack(ack: Mapping[str, Any], request: Mapping[str, Any]) -> None:
    required = {
        "contract_version", "automation_event_id", "automation_action", "lead_uid",
        "odoo_record_id", "result", "applied_fields", "unchanged_fields",
        "rejected_fields", "company_key", "business_unit_key", "campaign_key", "policy_version",
        "updated_at", "idempotent_replay",
    }
    if not required <= set(ack) or set(ack) - required - {"result_code"}:
        raise ContractError("ack fields do not match contract")
    if ack["contract_version"] != "1.1" or ack["result"] not in ACK_RESULTS:
        raise ContractError("invalid acknowledgement result")
    for field in (
        "automation_event_id", "automation_action", "company_key", "business_unit_key",
        "campaign_key", "policy_version",
    ):
        if ack[field] != request[field]:
            raise ContractError(f"ack {field} mismatch")
    if request.get("lead_uid") and ack["lead_uid"] != request["lead_uid"]:
        raise ContractError("ack lead mismatch")
    if ack["result"] == "FAILED" and not ack.get("result_code"):
        raise ContractError("FAILED acknowledgement requires result code")
