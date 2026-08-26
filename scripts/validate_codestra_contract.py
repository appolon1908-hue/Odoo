#!/usr/bin/env python3
"""Validate the Odoo integration identity and signed webhook contract."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "config" / "codestra-integration.json"
ISSUER = "https://auth.codestra.co/realms/codestra"
REQUIRED_HEADERS = {
    "Authorization",
    "Content-Type",
    "Idempotency-Key",
    "X-Codestra-Event-Id",
    "X-Codestra-Event-Type",
    "X-Codestra-Source",
    "X-Codestra-Tenant-Id",
    "X-Codestra-Timestamp",
    "X-Codestra-Signature",
    "X-Correlation-Id",
}
EVENT = re.compile(r"^codestra\.odoo\.(?:activity\.completed|lead\.(?:created|updated))$")


class ContractError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise ContractError(message)


def validate() -> None:
    try:
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"unable to load Odoo contract: {exc}")
    if not isinstance(contract, dict) or contract.get("schemaVersion") != 1:
        fail("schemaVersion must be 1")
    expected = {
        "sourceState": "adapter-source-missing",
        "issuer": ISSUER,
        "clientId": "odoo-integration",
        "clientType": "confidential",
        "grantType": "client_credentials",
        "serviceAccountsEnabled": True,
        "standardFlowEnabled": False,
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "fullScopeAllowed": False,
        "secretStorage": "odoo-system-parameters-and-protected-runtime-only",
    }
    for key, value in expected.items():
        if contract.get(key) != value:
            fail(f"{key} must equal {value!r}")
    lifetime = contract.get("maximumAccessTokenLifetimeSeconds")
    if not isinstance(lifetime, int) or not 1 <= lifetime <= 300:
        fail("machine-token lifetime must be 1..300 seconds")

    inbound = contract.get("inboundApi")
    if not isinstance(inbound, dict):
        fail("inboundApi must be an object")
    if inbound.get("baseUrlEnvironment") != "ODOO_INTEGRATION_BASE_URL":
        fail("Odoo adapter URL must use ODOO_INTEGRATION_BASE_URL")
    if inbound.get("audience") != "odoo-integration":
        fail("Odoo resource audience must be odoo-integration")
    if inbound.get("allowedCallers") != [
        {
            "clientId": "middleware-api",
            "scopes": [
                "odoo.activities.write",
                "odoo.leads.read",
                "odoo.leads.write",
            ],
        },
        {
            "clientId": "monitoring-readonly",
            "scopes": ["health.read", "metrics.read"],
        },
    ]:
        fail("Odoo caller or scope policy changed")

    outbound = contract.get("outboundMiddleware")
    if not isinstance(outbound, dict):
        fail("outboundMiddleware must be an object")
    if outbound.get("baseUrlEnvironment") != "MIDDLEWARE_API_BASE_URL":
        fail("middleware URL must use MIDDLEWARE_API_BASE_URL")
    if outbound.get("audience") != "middleware-api":
        fail("Odoo events must target middleware-api")
    if outbound.get("scopes") != [
        "odoo.delivery.result.publish",
        "odoo.events.publish",
    ]:
        fail("Odoo publish scopes changed")
    if outbound.get("eventPath") != "/api/v1/odoo/events":
        fail("canonical Odoo event path changed")
    if contract.get("prohibitedDirectCallers") != ["n8n-automation"]:
        fail("n8n must not call Odoo directly")

    security = contract.get("webhookSecurity")
    if not isinstance(security, dict):
        fail("webhookSecurity must be an object")
    for key, value in {
        "authorization": "oidc_bearer",
        "signatureAlgorithm": "hmac-sha256",
        "signatureVersion": "v1",
        "maximumClockSkewSeconds": 300,
        "replayRetentionSeconds": 86400,
        "delivery": "at_least_once",
        "idempotencyHeader": "X-Codestra-Event-Id",
    }.items():
        if security.get(key) != value:
            fail(f"webhookSecurity.{key} must equal {value!r}")
    if set(security.get("requiredHeaders", [])) != REQUIRED_HEADERS:
        fail("webhook required headers changed")

    events = contract.get("eventTypes")
    if (
        not isinstance(events, list)
        or events != sorted(events)
        or len(events) != len(set(events))
        or not all(isinstance(event, str) and EVENT.fullmatch(event) for event in events)
    ):
        fail("Odoo event types must be canonical, sorted, and unique")

    addon_entries = [path for path in (ROOT / "custom-addons").iterdir() if path.name != "README.md"]
    if addon_entries:
        fail("Odoo adapter source requires a separate reviewed implementation PR")

    print("ODOO_IDENTITY_POLICY=PASS")
    print("ODOO_API_AUDIENCE_POLICY=PASS")
    print("ODOO_WEBHOOK_POLICY=PASS")
    print("ODOO_ADAPTER_SOURCE_STATE=NOT_YET_IMPORTED")


if __name__ == "__main__":
    try:
        validate()
    except ContractError as exc:
        print(f"ODOO_CONTRACT_ERROR={exc}", file=sys.stderr)
        raise SystemExit(1)
