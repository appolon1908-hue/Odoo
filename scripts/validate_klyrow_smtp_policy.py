#!/usr/bin/env python3
"""Validate the secret-free, fail-closed Klyrow/Odoo SMTP policy."""

from __future__ import annotations

import ast
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "custom-addons" / "codestra_klyrow_smtp"
SHARED_DOMAINS = {
    "breero.com",
    "breero.shop",
    "codestra.agency",
    "codestra.cloud",
    "codestra.co",
    "codestra.digital",
    "codestra.media",
    "klyrow.com",
    "kyqra.com",
    "moneybee.loan",
    "moneybeeloan.com",
    "nativoenglish.com",
    "telnexa.co",
}
MANAGED_DOMAINS = SHARED_DOMAINS | {"beyvra.com"}
DRIFTED_INBOUND = MANAGED_DOMAINS - {"codestra.co", "klyrow.com"}


def _fields(record):
    return {
        field.attrib["name"]: (field.text or "").strip()
        if "eval" not in field.attrib
        else field.attrib["eval"]
        for field in record.findall("field")
    }


def main() -> int:
    errors: list[str] = []
    manifest_path = ADDON / "__manifest__.py"
    try:
        manifest = ast.literal_eval(manifest_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError) as exc:
        print(f"ERROR=invalid Klyrow SMTP manifest: {exc}", file=sys.stderr)
        return 1

    expected_data = {
        "security/ir.model.access.csv",
        "data/outgoing_mail_server_data.xml",
        "data/routing_policy_data.xml",
        "views/mail_routing_views.xml",
        "views/ir_mail_server_views.xml",
    }
    if set(manifest.get("data", [])) != expected_data:
        errors.append("manifest data inventory is incomplete")
    if manifest.get("version") != "19.0.1.0.0":
        errors.append("unexpected module version")

    server_xml = ADDON / "data" / "outgoing_mail_server_data.xml"
    try:
        tree = ET.parse(server_xml)
    except (OSError, ET.ParseError) as exc:
        print(f"ERROR=invalid outgoing server XML: {exc}", file=sys.stderr)
        return 1

    records = {
        record.attrib.get("id"): _fields(record)
        for record in tree.findall(".//record")
        if record.attrib.get("model") == "ir.mail_server"
    }
    if set(records) != {
        "mail_server_klyrow_production",
        "mail_server_beyvra_production",
    }:
        errors.append("exactly two governed server records are required")

    shared = records.get("mail_server_klyrow_production", {})
    beyvra = records.get("mail_server_beyvra_production", {})
    for label, record in (("shared", shared), ("beyvra", beyvra)):
        expected = {
            "smtp_host": "mail.klyrow.com",
            "smtp_port": "25",
            "smtp_encryption": "starttls_strict",
            "smtp_authentication": "login",
            "active": "False",
            "codestra_managed": "True",
            "codestra_secret_source": "/etc/klyrow/odoo-postal.env",
            "codestra_tracking_policy": "canonical_only",
            "codestra_tracking_host": "track.klyrow.com",
        }
        for field, value in expected.items():
            if record.get(field) != value:
                errors.append(f"{label}: {field} must be {value!r}")
        if "smtp_pass" in record:
            errors.append(f"{label}: SMTP password must not be present in XML")

    shared_filters = {
        part.strip()
        for part in shared.get("from_filter", "").split(",")
        if part.strip()
    }
    if shared_filters != SHARED_DOMAINS:
        errors.append("shared FROM filter does not match the exact 13 domains")
    if beyvra.get("from_filter") != "beyvra.com":
        errors.append("Beyvra FROM filter must be exact")
    if shared.get("smtp_user") != "klyrow/klyrow-production":
        errors.append("shared SMTP username drifted")
    if beyvra.get("smtp_user") != "klyrow/beyvra-production":
        errors.append("Beyvra SMTP username drifted")
    if shared.get("codestra_credential_state") != "hold":
        errors.append("shared credential must install held")
    if beyvra.get("codestra_credential_state") != "missing":
        errors.append("Beyvra credential must install missing")

    policy_path = ADDON / "integration" / "klyrow-domain-policy.json"
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR=invalid Klyrow domain policy: {exc}", file=sys.stderr)
        return 1

    profiles = policy.get("profiles", {})
    policy_domains = {
        domain
        for profile in profiles.values()
        for domain in profile.get("domains", [])
    }
    if policy_domains != MANAGED_DOMAINS:
        errors.append("policy must contain exactly 14 managed production domains")
    if set(policy["inbound"]["signed_adapter_active"]) != {
        "codestra.co",
        "klyrow.com",
    }:
        errors.append("signed inbound baseline must contain the exact two aligned domains")
    if set(policy["inbound"]["gmail_forwarding_drift"]) != DRIFTED_INBOUND:
        errors.append("inbound drift inventory must contain the other twelve domains")
    if policy["inbound"]["accepted_local_parts"] != ["support", "billing"]:
        errors.append("only support and billing may be routed to Odoo")
    if policy["inbound"]["prohibited_local_parts"] != ["admin", "appolon"]:
        errors.append("legacy admin and appolon local-parts must remain outside Odoo")
    if policy["tracking"] != {
        "allowed_path_prefix": "/t/",
        "custom_tracking_hosts_enabled": False,
        "host": "track.klyrow.com",
        "policy": "canonical_only",
        "root_application_exposure": False,
    }:
        errors.append("canonical tracking policy drifted")
    excluded = policy.get("excluded_domains", {})
    if set(excluded) != {"booked4seasons.com"}:
        errors.append("booked4seasons.com must be the exact excluded domain")

    helper = (ADDON / "scripts" / "provision_klyrow_smtp.py").read_text(
        encoding="utf-8"
    )
    if "smtp_pass" not in helper:
        errors.append("secret helper does not load the Odoo password field")
    if "KLYROW_LIVE_DELIVERY_ENABLED=NO" not in helper:
        errors.append("secret helper must report the closed delivery posture")
    if 'set_param(\n    "codestra.mail.live_delivery_enabled",\n    "false",' not in helper:
        errors.append("secret helper must force the Odoo live-delivery gate closed")
    if "print(shared_secret)" in helper or "print(beyvra_secret)" in helper:
        errors.append("secret helper must never print secret values")

    staging_env = (
        ROOT / "deploy" / "environments" / "staging.env.example"
    ).read_text(encoding="utf-8")
    for closed_flag in (
        "ENABLE_EXTERNAL_DELIVERY=false",
        "EMAIL_DELIVERY=false",
        "LIVE_EMAIL_DELIVERY=false",
    ):
        if closed_flag not in staging_env:
            errors.append(f"staging environment is missing {closed_flag}")

    model_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ADDON / "models").glob("*.py"))
    )
    for required in (
        "ENABLE_EXTERNAL_DELIVERY",
        "EMAIL_DELIVERY",
        "LIVE_EMAIL_DELIVERY",
        "_filter_mail_servers_fallback",
        "_find_mail_server",
        "send_email",
        "codestra_smtp_connection_test",
        "codestra_signed_inbound_adapter",
        "direct SMTP parameters",
        "booked4seasons.com",
        "track.klyrow.com",
    ):
        if required not in model_source:
            errors.append(f"model policy is missing {required!r}")

    if errors:
        print("Klyrow SMTP policy validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print("KLYROW_SMTP_MANAGED_DOMAINS=14")
    print("KLYROW_SMTP_SHARED_FILTER_DOMAINS=13")
    print("KLYROW_SMTP_BEYVRA_FILTER_DOMAINS=1")
    print("KLYROW_SIGNED_INBOUND_ALIGNED=2")
    print("KLYROW_SIGNED_INBOUND_DRIFT=12")
    print("KLYROW_SMTP_SECRETS_IN_GIT=0")
    print("KLYROW_SMTP_LIVE_DEFAULT=DISABLED")
    print("KLYROW_SMTP_POLICY=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
