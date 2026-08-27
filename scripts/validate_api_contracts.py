#!/usr/bin/env python3
"""Validate the complete canonical API inventory without overstating certification."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "tests" / "contracts" / "canonical-endpoints.json"
REQUIRED = {
    ("GET", "/healthz"),
    ("GET", "/readyz"),
    ("POST", "/events/vicidial"),
    ("POST", "/events/provider"),
    ("POST", "/screen-pop/resolve"),
    ("GET", "/interactions/{uuid}"),
    ("POST", "/interactions/{uuid}/disposition"),
    ("POST", "/interactions/{uuid}/callback"),
    ("POST", "/interactions/{uuid}/transfer"),
    ("GET", "/agents/me/state"),
    ("POST", "/agents/me/state"),
    ("GET", "/supervisor/queues"),
    ("POST", "/supervisor/actions"),
    ("GET", "/campaigns/{id}/configuration"),
    ("POST", "/campaigns/{id}/publish"),
    ("POST", "/provisioning/agents"),
    ("GET", "/provisioning/jobs/{uuid}"),
    ("POST", "/reconciliation/runs"),
    ("GET", "/reconciliation/runs/{uuid}"),
    ("GET", "/reports/operations"),
    ("GET", "/audit/events"),
}
ALLOWED_IMPLEMENTATION = {
    "implemented-in-canonical-addon",
    "adapter-required",
    "contract-only",
}


def main() -> int:
    errors: list[str] = []
    try:
        payload = json.loads(INVENTORY.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR=cannot load API inventory: {exc}", file=sys.stderr)
        return 1
    if payload.get("public_base") != "https://api.codestra.co/v1/contact-center":
        errors.append("canonical API base drifted")
    if payload.get("identity_issuer") != "https://auth.codestra.co/realms/codestra":
        errors.append("canonical identity issuer drifted")
    if payload.get("certification_status") != "blocked-runtime-evidence":
        errors.append("API inventory must remain blocked until runtime evidence exists")

    endpoints = payload.get("endpoints", [])
    actual = {(item.get("method"), item.get("path")) for item in endpoints if isinstance(item, dict)}
    if actual != REQUIRED:
        errors.append(
            "API inventory mismatch: missing="
            + ",".join(f"{method} {path}" for method, path in sorted(REQUIRED - actual))
            + " extra="
            + ",".join(f"{method} {path}" for method, path in sorted(actual - REQUIRED))
        )
    if len(actual) != len(endpoints):
        errors.append("API inventory contains duplicate or invalid endpoint entries")
    for item in endpoints:
        if item.get("implementation_status") not in ALLOWED_IMPLEMENTATION:
            errors.append(f"invalid implementation status for {item.get('method')} {item.get('path')}")
        if item.get("certification_status") != "blocked-runtime-evidence":
            errors.append(f"endpoint incorrectly claims certification: {item.get('method')} {item.get('path')}")
        if not isinstance(item.get("permission"), str) or not item["permission"]:
            errors.append(f"endpoint is missing a permission: {item.get('method')} {item.get('path')}")

    if errors:
        print("API contract validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(f"CANONICAL_API_ENDPOINTS={len(REQUIRED)}")
    print("CANONICAL_API_SOURCE_INVENTORY=PASS")
    print("CANONICAL_API_RUNTIME_CERTIFICATION=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
