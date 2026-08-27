#!/usr/bin/env python3
"""Fail closed when mission modules add unsafe authority or live capability."""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDONS = ROOT / "custom-addons"
COVERAGE = ROOT / "config" / "call-center-module-coverage.json"
SAFETY = ROOT / "config" / "mission-safety-policy.json"
FORBIDDEN_SOURCE = {
    ".sudo(": "unrestricted sudo call",
    ".env.cr.execute(": "raw SQL outside migration",
    "request.env.cr.execute(": "raw SQL outside migration",
    "requests.": "direct external HTTP client",
    "httpx.": "direct external HTTP client",
    "urllib.request": "direct external HTTP client",
    "socket.": "direct network socket",
}
SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:password|passwd|pwd|client_secret|api_token|private_key)\s*[:=]\s*['\"][^'\"]+['\"]"
)
PUBLIC_ROUTE = re.compile(r"@http\.route[\s\S]{0,500}?auth\s*=\s*['\"](?:public|none)['\"]")
PROHIBITED_AI_METHODS = {
    "send_customer_message",
    "send_message",
    "set_consent",
    "set_dnc",
    "approve_refund",
    "finalize_disposition",
    "execute_provider_action",
}


def module_names() -> list[str]:
    payload = json.loads(COVERAGE.read_text(encoding="utf-8"))
    return sorted(item["mission_module"] for item in payload["coverage"])


def validate_manifest(module: Path, errors: list[str]) -> None:
    manifest = ast.literal_eval((module / "__manifest__.py").read_text(encoding="utf-8"))
    if manifest.get("post_init_hook") or manifest.get("pre_init_hook") or manifest.get("uninstall_hook"):
        errors.append(f"{module.name}: mission modules may not run install or uninstall hooks")


def main() -> int:
    errors: list[str] = []
    try:
        policy = json.loads(SAFETY.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR=cannot load mission safety policy: {exc}", file=sys.stderr)
        return 1
    capabilities = policy.get("live_capabilities")
    if not isinstance(capabilities, dict) or not capabilities:
        errors.append("live_capabilities must be a non-empty object")
    elif any(value is not False for value in capabilities.values()):
        errors.append("every live capability must remain false")
    if policy.get("test_data", {}).get("synthetic_only") is not True:
        errors.append("test data must remain synthetic-only")

    for name in module_names():
        module = ADDONS / name
        try:
            validate_manifest(module, errors)
        except (OSError, SyntaxError, ValueError) as exc:
            errors.append(f"{name}: cannot validate manifest: {exc}")
            continue
        for path in sorted(module.rglob("*.py")):
            relative = path.relative_to(ROOT)
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                errors.append(f"{relative}: cannot read source: {exc}")
                continue
            lowered = text.lower().replace(" ", "")
            for token, label in FORBIDDEN_SOURCE.items():
                if token in lowered:
                    errors.append(f"{relative}: contains {label}")
            if SECRET_ASSIGNMENT.search(text):
                errors.append(f"{relative}: appears to embed secret material")
            if PUBLIC_ROUTE.search(text):
                errors.append(f"{relative}: public or unauthenticated controller is prohibited")

    ai_path = ADDONS / "codestra_ai_agent_assistant" / "models" / "assistant_draft.py"
    ai_tree = ast.parse(ai_path.read_text(encoding="utf-8"), filename=str(ai_path))
    method_names = {
        node.name
        for node in ast.walk(ai_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    prohibited = method_names & PROHIBITED_AI_METHODS
    if prohibited:
        errors.append("AI assistant exposes prohibited authority: " + ", ".join(sorted(prohibited)))

    portal = ADDONS / "codestra_client_portal" / "controllers" / "portal.py"
    portal_text = portal.read_text(encoding="utf-8").lower().replace(" ", "")
    if ".sudo(" in portal_text:
        errors.append("client portal controller may not bypass record rules")
    if 'auth="user"' not in portal_text and "auth='user'" not in portal_text:
        errors.append("client portal routes must require authenticated users")

    if errors:
        print("Mission security validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(f"LIVE_CAPABILITIES_CLOSED={len(capabilities)}")
    print("MISSION_DIRECT_NETWORK_WRITERS=0")
    print("MISSION_UNRESTRICTED_SUDO=0")
    print("MISSION_PUBLIC_CONTROLLERS=0")
    print("MISSION_SECURITY_SOURCE_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
