#!/usr/bin/env python3
"""Validate the Odoo side of the observability control plane.

Pinned consumer of appolon1908-hue/Middleware-'s canonical
contracts/observability-control-plane.v1.json (same pinning convention as
this repo's existing contracts/platform-control-plane.v1.json +
scripts/validate_platform_control_plane.py, which this file is styled
after: AST/text scan the real routes, fail() on drift).

The important negative check for Odoo specifically: nothing in this
repo may receive Alertmanager's webhook payload shape - Alertmanager
sends alerts to Middleware only, never here.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "observability-control-plane.v1.json"
ADDONS = ROOT / "custom-addons"

# A route is treated as "Alertmanager-shaped" if its handler mentions any
# of these - the same vocabulary Alertmanager's own native webhook payload
# uses (group labels/annotations, receiver, alert status) - a much lower
# bar than requiring an exact model name, so this catches a reimplementation
# under a different name too, not just a literal copy-paste.
ALERTMANAGER_PAYLOAD_MARKERS = (
    "groupLabels", "groupKey", "commonLabels", "commonAnnotations",
    "externalURL", "alertname", "AlertmanagerWebhook",
)


def fail(message: str) -> None:
    raise SystemExit(f"OBSERVABILITY_CONTROL_PLANE=FAIL {message}")


def find_metrics_route(source: str, path: str) -> bool:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "route"
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and decorator.args[0].value == path
            ):
                continue
            return True
    return False


def main() -> int:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    if contract.get("contract_id") != "codestra.observability-control-plane":
        fail("unexpected contract identity")
    if contract.get("canonical_owner") != "appolon1908-hue/Middleware-":
        fail("Middleware is not the declared canonical owner")
    if contract.get("source_repository") != "appolon1908-hue/Middleware-":
        fail("pinned contract is missing its source_repository pin")
    if not contract.get("source_commit"):
        fail("pinned contract is missing its source_commit pin")

    odoo_endpoints = contract.get("endpoints", {}).get("appolon1908-hue/Odoo")
    if odoo_endpoints is None:
        fail("canonical contract no longer declares an Odoo endpoints entry")
    if odoo_endpoints.get("alertmanager_receiver_present") is not False:
        fail("contract no longer asserts Odoo has no Alertmanager receiver")

    alertmanager_service = next(
        (s for s in contract["services"] if s["service"] == "alertmanager"), None
    )
    if alertmanager_service is None or alertmanager_service.get("authorized_receiver") != (
        "appolon1908-hue/Middleware-"
    ):
        fail("contract no longer names Middleware as the sole Alertmanager receiver")

    # The important negative check: scan every controller in this repo for
    # anything that looks like it accepts an Alertmanager-shaped payload.
    # If the /codestra/metrics endpoint this contract expects has merged,
    # also confirm it's actually registered - but its absence pre-merge is
    # not itself a failure (the contract records it as pending_merge).
    metrics_path = odoo_endpoints.get("metrics_path")
    metrics_addon = odoo_endpoints.get("metrics_owning_addon")
    metrics_found = False
    for controller_path in ADDONS.rglob("controllers/*.py"):
        text = controller_path.read_text(encoding="utf-8", errors="replace")
        for marker in ALERTMANAGER_PAYLOAD_MARKERS:
            if marker in text:
                fail(
                    f"{controller_path.relative_to(ROOT)} contains an "
                    f"Alertmanager-shaped payload marker ({marker!r}) - "
                    "Alertmanager must send alerts to Middleware only"
                )
        if (
            metrics_path
            and metrics_addon
            and controller_path.parts[len(ADDONS.parts)] == metrics_addon
            and find_metrics_route(text, metrics_path)
        ):
            metrics_found = True

    if odoo_endpoints.get("status") == "live" and not metrics_found:
        fail(
            f"contract says Odoo's {metrics_path} endpoint is live but no "
            f"route for it was found in {metrics_addon}"
        )

    print("OBSERVABILITY_CONTROL_PLANE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
