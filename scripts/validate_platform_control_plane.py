#!/usr/bin/env python3
"""Fail CI if the Odoo side of the four-repository control plane drifts."""

from __future__ import annotations

import ast
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
INTEGRATION_POLICY = ROOT / "config" / "integration-boundary.json"


def fail(message: str) -> None:
    raise SystemExit(f"PLATFORM_CONTROL_PLANE=FAIL {message}")


def function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    if len(matches) != 1:
        fail(f"expected exactly one controller function named {name}")
    return ast.get_source_segment(source, matches[0]) or ""


def validated_routes(source: str) -> dict[str, tuple[set[str], bool]]:
    routes: dict[str, tuple[set[str], bool]] = {}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        begin_calls = [
            call
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "_begin"
        ]
        replay_protected = any(
            any(
                keyword.arg == "allow_event_replay"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in call.keywords
            )
            for call in begin_calls
        )
        for decorator in node.decorator_list:
            if not (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "route"
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and isinstance(decorator.args[0].value, str)
            ):
                continue
            methods: set[str] = set()
            for keyword in decorator.keywords:
                if keyword.arg == "methods" and isinstance(
                    keyword.value, (ast.List, ast.Tuple)
                ):
                    methods = {
                        item.value
                        for item in keyword.value.elts
                        if isinstance(item, ast.Constant)
                        and isinstance(item.value, str)
                    }
            routes[decorator.args[0].value] = (methods, replay_protected)
    return routes


def main() -> int:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    policy = json.loads(INTEGRATION_POLICY.read_text(encoding="utf-8"))
    source = CONTROLLER.read_text(encoding="utf-8")

    if contract.get("contract_id") != "codestra.platform-control-plane":
        fail("unexpected contract identity")
    if contract.get("status") != "PREPARED_DISABLED":
        fail("integration must remain prepared/disabled before staging activation")
    if contract.get("decision") != "middleware_adopts_automation_v2":
        fail("automation authority decision drifted")

    repositories = contract.get("repositories", {})
    if repositories.get("business_authority") != "appolon1908-hue/Odoo":
        fail("Odoo repository is not the declared business authority")
    if repositories.get("write_authority") != "appolon1908-hue/Middleware-":
        fail("Middleware is not the declared cross-system write authority")
    if repositories.get("orchestration") != "appolon1908-hue/N8N":
        fail("N8N is not the declared orchestration authority")
    if repositories.get("gateway_authority") != "appolon1908-hue/Kong":
        fail("Kong is not the declared gateway authority")

    automation = contract.get("n8n_to_middleware", {})
    expected_automation = {
        "canonical_submit_path": "/v2/automation/commands",
        "canonical_read_path": "/v2/automation/commands/{command_id}",
        "client_id": "n8n-crm-automation",
        "audience": "middleware-api",
        "submit_scope": "automation.command.crm",
        "read_scope": "automation.command.read",
        "tenant_authority": "verified_token_and_durable_job",
        "header_body_agreement_required": True,
        "direct_provider_access": False,
    }
    for key, value in expected_automation.items():
        if automation.get(key) != value:
            fail(f"automation contract field {key} drifted")
    aliases = automation.get("compatibility_aliases", [])
    if {
        item.get("path")
        for item in aliases
        if isinstance(item, dict) and item.get("status") == "deprecated"
    } != {
        "/v1/integrations/n8n/commands",
        "/v1/integrations/n8n/operations/{command_id}",
    }:
        fail("legacy n8n compatibility aliases drifted")

    boundary = contract.get("middleware_to_odoo", {})
    expected = {
        "target": "odoo-19",
        "capability": "ODOO_WRITE",
        "bridge_module": "codestra_middleware_bridge",
        "canonical_command_type": "crm.lead.upsert",
        "canonical_command_version": "1.0",
        "canonical_command_path": "/codestra/middleware/v1/commands/crm.lead.upsert",
        "canonical_status_path": "/codestra/middleware/v1/commands/{command_id}/status",
        "readback_required": True,
        "unknown_outcome_policy": "query_command_status_before_any_retry",
        "blind_resubmission_allowed": False,
    }
    for key, value in expected.items():
        if boundary.get(key) != value:
            fail(f"Odoo contract field {key} drifted")

    canonical_fields = boundary.get("hmac_canonical_fields_in_order")
    expected_fields = [
        "X-Codestra-Timestamp",
        "X-Codestra-Event-ID",
        "HTTP_METHOD_UPPERCASE",
        "REQUEST_PATH",
        "X-Tenant-ID",
        "X-Correlation-ID",
        "Idempotency-Key",
        "RAW_REQUEST_BODY",
    ]
    if canonical_fields != expected_fields:
        fail("HMAC canonical field order drifted")

    bridge = policy.get("orm_bridge", {})
    if bridge.get("module_name") != "codestra_middleware_bridge":
        fail("machine integration policy names a non-canonical bridge module")
    if bridge.get("canonical_command_path") != expected["canonical_command_path"]:
        fail("machine integration policy command path drifted")
    if bridge.get("canonical_status_path") != expected["canonical_status_path"]:
        fail("machine integration policy status path drifted")
    if bridge.get("blind_resubmission_after_unknown_outcome_allowed") is not False:
        fail("unknown-outcome blind resubmission must remain prohibited")

    authenticate_source = function_source(source, "_authenticate")
    required_authentication_markers = (
        'headers.get("X-Codestra-Timestamp", "")',
        'headers.get("X-Codestra-Event-ID", "")',
        'headers.get("X-Codestra-Signature", "")',
        'headers.get("X-Tenant-ID", "")',
        'headers.get("X-Correlation-ID", "")',
        'headers.get("Idempotency-Key", "")',
        "tenant.encode(), correlation.encode(), idempotency.encode()",
        "hmac.compare_digest",
    )
    missing = [
        marker
        for marker in required_authentication_markers
        if marker not in authenticate_source
    ]
    if missing:
        fail(
            "_authenticate no longer proves required security markers: "
            + ", ".join(missing)
        )

    begin_source = function_source(source, "_begin")
    required_begin_markers = (
        "self._authenticate(",
        '"idempotency_conflict"',
        '"replayed_event_id"',
    )
    missing = [marker for marker in required_begin_markers if marker not in begin_source]
    if missing:
        fail("_begin no longer proves required security markers: " + ", ".join(missing))

    command_source = function_source(source, "_command_to_crm_payload")
    for marker in (
        'command.get("command_type") != "crm.lead.upsert"',
        'command.get("command_version") != "1.0"',
        'command.get("target") != "odoo-19"',
        'command.get("capability") != "ODOO_WRITE"',
        'command.get("command_id") != auth["event_id"]',
        'command.get("tenant_id") != auth["tenant_id"]',
        'command.get("correlation_id") != auth["correlation_id"]',
        'command.get("idempotency_key") != auth["idempotency_key"]',
    ):
        if marker not in command_source:
            fail(f"canonical CRM command validation marker is missing: {marker}")

    expected_routes = {
        "/codestra/middleware/v1/commands/crm.lead.upsert": {"POST"},
        "/codestra/middleware/v1/commands/<string:command_id>/status": {"GET"},
    }
    actual_routes = validated_routes(source)
    for path, methods in expected_routes.items():
        actual = actual_routes.get(path)
        if actual is None:
            fail(f"required controller route is missing: {path}")
        actual_methods, replay_protected = actual
        if actual_methods != methods:
            fail(f"route methods drifted for {path}")
        if not replay_protected:
            fail(f"route no longer invokes replay-protected _begin: {path}")

    compatibility_routes = {
        "/codestra/middleware/v1/crm/leads",
        "/codestra/middleware/v1/crm/leads/<string:external_id>",
        "/codestra/middleware/v1/crm/activities",
    }
    if not compatibility_routes <= set(actual_routes):
        fail("declared Odoo compatibility routes are missing")

    safety = contract.get("safety", {})
    for flag in ("ODOO_WRITE", "ENABLE_EXTERNAL_DELIVERY", "LIVE_WRITE"):
        if safety.get(flag) is not False:
            fail(f"{flag} must remain false in source-integration contract")
    if safety.get("secrets_in_git") is not False:
        fail("contract must prohibit secrets in Git")
    if safety.get("deployment_permitted_by_contract") is not False:
        fail("source contract must not grant deployment authority")

    serialized = (CONTRACT.read_text(encoding="utf-8") + INTEGRATION_POLICY.read_text(encoding="utf-8")).lower()
    for forbidden in ("client_secret", "password", "access_token", "private_key"):
        if forbidden in serialized:
            fail(f"contract contains forbidden secret-bearing field: {forbidden}")

    print("PLATFORM_CONTROL_PLANE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
