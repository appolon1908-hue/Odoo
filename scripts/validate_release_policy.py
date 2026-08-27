#!/usr/bin/env python3
"""Validate manual, non-publishing, non-deploying release-candidate construction."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "release-policy.json"
WORKFLOW = ROOT / ".github" / "workflows" / "cc-release-candidate.yml"
ENV_EXAMPLE = ROOT / "deploy" / "environments" / "staging.env.example"
PINNED_ACTION = re.compile(r"uses:\s+[^\s@]+@[0-9a-f]{40}(?:\s+#.*)?$")


def main() -> int:
    errors: list[str] = []
    try:
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR=cannot load release policy: {exc}", file=sys.stderr)
        return 1
    expected_false = (
        "automatic_publish",
        "automatic_deploy",
        "automatic_signing",
        "runtime_environment_changes",
    )
    for key in expected_false:
        if policy.get(key) is not False:
            errors.append(f"release policy {key} must be false")
    if policy.get("workflow_dispatch_only") is not True:
        errors.append("release workflow must remain manual")
    if len(policy.get("required_branch_order", [])) != 11:
        errors.append("release policy must contain the complete eleven-branch stack")

    workflow = WORKFLOW.read_text(encoding="utf-8") if WORKFLOW.is_file() else ""
    for required in (
        "workflow_dispatch:",
        "permissions:\n  contents: read",
        "persist-credentials: false",
        "bash scripts/run_ci.sh",
        "bash scripts/build_release_candidate.sh",
        "SOURCE_TESTS_STATUS: PASS",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
    ):
        if required not in workflow:
            errors.append(f"release workflow is missing {required!r}")
    for forbidden in (
        "push:\n",
        "pull_request:\n",
        "docker push",
        "gh release",
        "kubectl ",
        "docker compose up",
        "ssh ",
        "rsync ",
    ):
        if forbidden in workflow.lower():
            errors.append(f"release workflow contains prohibited operation {forbidden.strip()!r}")
    action_lines = [
        line.strip()
        for line in workflow.splitlines()
        if line.strip().startswith("uses:")
    ]
    if not action_lines or any(not PINNED_ACTION.fullmatch(line) for line in action_lines):
        errors.append("every release workflow action must be pinned to a 40-character commit SHA")

    env_text = ENV_EXAMPLE.read_text(encoding="utf-8") if ENV_EXAMPLE.is_file() else ""
    for flag in (
        "LIVE_ODOO_WRITE=false",
        "ENABLE_EXTERNAL_DELIVERY=false",
        "EMAIL_DELIVERY=false",
        "SMS_DELIVERY=false",
        "CALLBACK_DISPATCH=false",
        "PSTN_DIALING=false",
        "N8N_ACTIVATION=false",
        "VICIDIAL_LIVE_CONTROL=false",
    ):
        if flag not in env_text:
            errors.append(f"staging example is missing closed flag {flag}")
    if re.search(
        r"(?i)(?:password|secret|token|private_key)\s*=\s*\S+",
        env_text,
    ):
        errors.append("staging example must not contain credential values or placeholders")

    if errors:
        print("Release policy validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("RELEASE_WORKFLOW_DISPATCH_ONLY=PASS")
    print("RELEASE_ACTIONS_PINNED=PASS")
    print("AUTOMATIC_PUBLISH=DISABLED")
    print("AUTOMATIC_DEPLOY=DISABLED")
    print("STAGING_LIVE_CAPABILITIES=CLOSED")
    print("RELEASE_POLICY_SOURCE_GATE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
