#!/usr/bin/env python3
"""Validate the sanitized corporate call-center workstream contract."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "call-center-workstreams.json"
MISSION = ROOT / "docs" / "missions" / "CODESTRA-CORPORATE-CALL-CENTER.md"
BRANCHES = ROOT / "docs" / "branches" / "CALL-CENTER-BRANCH-STACK.md"
OPENAPI = ROOT / "api" / "openapi" / "contact-center-v1.yaml"

BRANCH_RE = re.compile(r"^(?:feature|test|release)/cc-\d{2}-[a-z0-9-]+$")
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
REQUIRED_MODULES = {
    "codestra_cc_core",
    "codestra_cc_vicidial",
    "codestra_cc_agent_desktop",
    "codestra_cc_campaign",
    "codestra_cc_disposition",
    "codestra_cc_customer_360",
    "codestra_cc_supervisor",
    "codestra_cc_quality",
    "codestra_cc_compliance",
    "codestra_cc_omnichannel",
    "codestra_cc_workforce",
    "codestra_cc_identity",
    "codestra_cc_mailbox",
    "codestra_cc_automation",
    "codestra_cc_reliability",
    "codestra_cc_analytics",
    "codestra_cc_audit",
    "codestra_client_operations",
    "codestra_revenue_assurance",
    "codestra_data_quality",
    "codestra_case_management",
    "codestra_agent_onboarding",
    "codestra_training_academy",
    "codestra_client_portal",
    "codestra_campaign_publishing",
    "codestra_ai_agent_assistant",
}
REQUIRED_ENDPOINTS = {
    "/v1/contact-center/healthz",
    "/v1/contact-center/readyz",
    "/v1/contact-center/events/vicidial",
    "/v1/contact-center/events/provider",
    "/v1/contact-center/screen-pop/resolve",
    "/v1/contact-center/interactions/{interaction_uuid}",
    "/v1/contact-center/interactions/{interaction_uuid}/disposition",
    "/v1/contact-center/interactions/{interaction_uuid}/callback",
    "/v1/contact-center/interactions/{interaction_uuid}/transfer",
    "/v1/contact-center/agents/me/state",
    "/v1/contact-center/supervisor/queues",
    "/v1/contact-center/supervisor/actions",
    "/v1/contact-center/campaigns/{campaign_id}/configuration",
    "/v1/contact-center/campaigns/{campaign_id}/publish",
    "/v1/contact-center/provisioning/agents",
    "/v1/contact-center/provisioning/jobs/{job_uuid}",
    "/v1/contact-center/reconciliation/runs",
    "/v1/contact-center/reconciliation/runs/{run_uuid}",
    "/v1/contact-center/reports/operations",
    "/v1/contact-center/audit/events",
}
CLOSED_CAPABILITIES = {
    "live_odoo_write",
    "external_delivery",
    "email_delivery",
    "sms_delivery",
    "pstn_dialing",
    "callback_dispatch",
    "n8n_activation",
}


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def load_text(path: Path, errors: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        fail(errors, f"cannot read {path.relative_to(ROOT)}: {exc}")
        return ""


def main() -> int:
    errors: list[str] = []

    try:
        registry_text = REGISTRY.read_text(encoding="utf-8")
        registry = json.loads(registry_text)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR=cannot load {REGISTRY.relative_to(ROOT)}: {exc}", file=sys.stderr)
        return 1

    if IPV4_RE.search(registry_text):
        fail(errors, "workstream registry contains a host address")
    if registry.get("schema_version") != 1:
        fail(errors, "schema_version must be 1")

    public_safety = registry.get("public_repository_safety", {})
    for key in (
        "raw_mission_committed",
        "host_addresses_allowed",
        "credentials_allowed",
        "customer_data_allowed",
    ):
        if public_safety.get(key) is not False:
            fail(errors, f"public_repository_safety.{key} must be false")

    contracts = registry.get("canonical_contracts", {})
    if contracts.get("api_base_path") != "/v1/contact-center/":
        fail(errors, "canonical API base path drifted")
    if contracts.get("identity_issuer") != "https://auth.codestra.co/realms/codestra":
        fail(errors, "canonical identity issuer drifted")
    if contracts.get("cross_system_writer") != "codestra-middleware":
        fail(errors, "Middleware-only write boundary drifted")
    for key in (
        "odoo_core_modification_allowed",
        "vicidial_database_writes_allowed",
        "n8n_system_of_record_allowed",
    ):
        if contracts.get(key) is not False:
            fail(errors, f"canonical_contracts.{key} must be false")

    capabilities = registry.get("default_capabilities", {})
    if set(capabilities) != CLOSED_CAPABILITIES:
        missing = sorted(CLOSED_CAPABILITIES - set(capabilities))
        extra = sorted(set(capabilities) - CLOSED_CAPABILITIES)
        fail(errors, f"default capability keys mismatch; missing={missing}, extra={extra}")
    for key in CLOSED_CAPABILITIES:
        if capabilities.get(key) is not False:
            fail(errors, f"default capability {key} must be false")

    workstreams = registry.get("workstreams")
    if not isinstance(workstreams, list) or not workstreams:
        fail(errors, "workstreams must be a non-empty list")
        workstreams = []

    orders = [item.get("order") for item in workstreams if isinstance(item, dict)]
    if orders != list(range(11)):
        fail(errors, f"workstream orders must be exactly 0 through 10; got {orders}")

    branches: list[str] = []
    module_owners: dict[str, str] = {}
    known_dependencies = {"feature/codestra-login-admin-readiness"}
    for item in workstreams:
        if not isinstance(item, dict):
            fail(errors, "each workstream must be an object")
            continue

        branch = item.get("branch")
        if not isinstance(branch, str) or not BRANCH_RE.fullmatch(branch):
            fail(errors, f"invalid workstream branch name: {branch!r}")
            continue
        if branch in branches:
            fail(errors, f"duplicate workstream branch: {branch}")
        branches.append(branch)

        dependencies = item.get("depends_on")
        if not isinstance(dependencies, list) or not dependencies:
            fail(errors, f"{branch}: depends_on must be a non-empty list")
            dependencies = []
        for dependency in dependencies:
            if dependency not in known_dependencies:
                fail(errors, f"{branch}: unknown or forward dependency {dependency!r}")

        modules = item.get("modules")
        if not isinstance(modules, list):
            fail(errors, f"{branch}: modules must be a list")
            modules = []
        for module in modules:
            if not isinstance(module, str) or not re.fullmatch(r"[a-z][a-z0-9_]+", module):
                fail(errors, f"{branch}: invalid module name {module!r}")
                continue
            previous = module_owners.get(module)
            if previous:
                fail(errors, f"module {module} owned by both {previous} and {branch}")
            module_owners[module] = branch

        deliverables = item.get("deliverables")
        if not isinstance(deliverables, list) or not deliverables:
            fail(errors, f"{branch}: deliverables must be a non-empty list")

        known_dependencies.add(branch)

    owned_modules = set(module_owners)
    if owned_modules != REQUIRED_MODULES:
        fail(
            errors,
            "module registry mismatch; "
            f"missing={sorted(REQUIRED_MODULES - owned_modules)}, "
            f"extra={sorted(owned_modules - REQUIRED_MODULES)}",
        )

    for path in (MISSION, BRANCHES):
        text = load_text(path, errors)
        if IPV4_RE.search(text):
            fail(errors, f"{path.relative_to(ROOT)} contains a host address")
        for required in (
            "LIVE_ODOO_WRITE=false",
            "ENABLE_EXTERNAL_DELIVERY=false",
            "PSTN_DIALING=false",
        ):
            if path == MISSION and required not in text:
                fail(errors, f"{path.relative_to(ROOT)} missing safety default {required}")

    openapi_text = load_text(OPENAPI, errors)
    if IPV4_RE.search(openapi_text):
        fail(errors, f"{OPENAPI.relative_to(ROOT)} contains a host address")
    for token in (
        "openapi: 3.1.0",
        "x-codestra-implementation-status: contract-only",
        "odoo_write: false",
        "external_delivery: false",
        "openIdConnectUrl: https://auth.codestra.co/realms/codestra/.well-known/openid-configuration",
    ):
        if token not in openapi_text:
            fail(errors, f"OpenAPI contract missing {token!r}")
    for endpoint in sorted(REQUIRED_ENDPOINTS):
        if f"  {endpoint}:" not in openapi_text:
            fail(errors, f"OpenAPI contract missing endpoint {endpoint}")

    if errors:
        print("Call-center workstream validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"CALL_CENTER_WORKSTREAMS={len(workstreams)}")
    print(f"CALL_CENTER_MODULES={len(module_owners)}")
    print(f"CALL_CENTER_API_PATHS={len(REQUIRED_ENDPOINTS)}")
    print("CALL_CENTER_PUBLIC_REPOSITORY_SANITIZATION=PASS")
    print("CALL_CENTER_CAPABILITY_DEFAULTS=CLOSED")
    print("CALL_CENTER_WORKSTREAM_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
