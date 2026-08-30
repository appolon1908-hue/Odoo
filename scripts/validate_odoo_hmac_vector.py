#!/usr/bin/env python3
"""Validate the synthetic byte-exact Middleware-to-Odoo HMAC vector."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VECTOR = ROOT / "contracts" / "odoo-hmac-test-vector.v1.json"


def fail(message: str) -> None:
    raise SystemExit(f"ODOO_HMAC_VECTOR=FAIL {message}")


def main() -> int:
    vector = json.loads(VECTOR.read_text(encoding="utf-8"))
    if vector.get("schema_version") != "1.0":
        fail("schema version drifted")
    if vector.get("secret") != "test-secret-not-production":
        fail("the committed vector must remain synthetic")
    try:
        document = json.loads(vector["body_utf8"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        fail(f"body_utf8 is not canonical JSON: {exc}")
    canonical_body = json.dumps(
        document,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if canonical_body != vector["body_utf8"]:
        fail("body_utf8 is not the sorted canonical adapter body")
    canonical = "\n".join(
        (
            vector["timestamp"],
            vector["event_id"],
            vector["method"].upper(),
            vector["path"],
            vector["tenant_id"],
            vector["correlation_id"],
            vector["idempotency_key"],
            vector["body_utf8"],
        )
    ).encode("utf-8")
    digest = hmac.new(
        vector["secret"].encode("utf-8"), canonical, hashlib.sha256
    ).hexdigest()
    if digest != vector.get("expected_hmac_sha256_hex"):
        fail("expected HMAC digest does not match the canonical bytes")
    if document.get("command_type") != "crm.lead.upsert":
        fail("command type drifted")
    if document.get("command_version") != "1.0":
        fail("command version drifted")
    if document.get("target") != "odoo-19":
        fail("command target drifted")
    if document.get("capability") != "ODOO_WRITE":
        fail("command capability drifted")
    for header_key, document_key in (
        ("tenant_id", "tenant_id"),
        ("correlation_id", "correlation_id"),
        ("idempotency_key", "idempotency_key"),
    ):
        if vector.get(header_key) != document.get(document_key):
            fail(f"{header_key} does not agree with the canonical body")
    print("ODOO_HMAC_VECTOR=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
