#!/usr/bin/env python3
"""Fail CI if the Odoo side of the four-repository control plane drifts."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "platform-control-plane.v1.json"
CONTROLLER = (
    ROOT
    / "custom-addons"
    / "codestra_middleware_bridge"
    / "controllers"
    / "api.py"
)


def fail(message: str) -> None:
    raise SystemExit(f"PLATFORM_CONTROL_PLANE=FAIL {message}")


def main() -> int:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    source = CONTROLLER.read_text(encoding="utf-8")

    if contract.get("contract_id") != "codestra.platform-control-plane":
        fail("unexpected contract identity")
    if contract.get("status") != "PREPARED_DISABLED":
        fail("integration must remain prepared/disabled before staging activation")

    repositories = contract.get("repositories", {})
    if repositories.get("business_authority") != "appolon1908-hue/Odoo":
        fail("Odoo repository is not the declared business authority")
    if repositories.get("write_authority") != "appolon1908-hue/Middleware-":
        fail("Middleware is not the declared cross-system write authority")
    if repositories.get("orchestration") != "appolon1908-hue/N8N":
        fail("N8N is not the declared orchestration authority")
    if repositories.get("gateway_authority") != "appolon1908-hue/Kong":
        fail("Kong is not the declared gateway authority")

    boundary = contract.get("middleware_to_odoo", {})
    expected = {
        "target": "odoo-19",
        "capability": "ODOO_WRITE",
        "create_lead_path": "/codestra/middleware/v1/crm/leads",
        "lead_path": "/codestra/middleware/v1/crm/leads/{external_id}",
        "activity_path": "/codestra/middleware/v1/crm/activities",
        "readback_required": True,
    }
    for key, value in expected.items():
        if boundary.get(key) != value:
            fail(f"contract field {key} drifted")

    required_source_markers = (
        '@http.route("/codestra/middleware/v1/crm/leads",',
        '@http.route("/codestra/middleware/v1/crm/leads/<string:external_id>",',
        '@http.route("/codestra/middleware/v1/crm/activities",',
        'headers.get("X-Codestra-Timestamp", "")',
        'headers.get("X-Codestra-Event-ID", "")',
        'headers.get("X-Codestra-Signature", "")',
        'headers.get("X-Tenant-ID", "")',
        'headers.get("X-Correlation-ID", "")',
        'headers.get("Idempotency-Key", "")',
        "hmac.compare_digest",
        '"idempotency_conflict"',
        '"replayed_event_id"',
    )
    missing = [marker for marker in required_source_markers if marker not in source]
    if missing:
        fail("controller no longer proves required boundary markers: " + ", ".join(missing))

    safety = contract.get("safety", {})
    for flag in ("ODOO_WRITE", "ENABLE_EXTERNAL_DELIVERY", "LIVE_WRITE"):
        if safety.get(flag) is not False:
            fail(f"{flag} must remain false in source-integration contract")
    if safety.get("secrets_in_git") is not False:
        fail("contract must prohibit secrets in Git")
    if safety.get("deployment_permitted_by_contract") is not False:
        fail("source contract must not grant deployment authority")

    serialized = CONTRACT.read_text(encoding="utf-8").lower()
    for forbidden in ("client_secret", "password", "access_token", "private_key"):
        if forbidden in serialized:
            fail(f"contract contains forbidden secret-bearing field: {forbidden}")

    print("PLATFORM_CONTROL_PLANE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
