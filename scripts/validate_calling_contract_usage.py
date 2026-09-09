#!/usr/bin/env python3
"""Fail closed when Odoo's telephony surface drifts from the pinned authority.

validate_calling_contract_pin.py proves the vendored calling contract is the
reviewed authority byte for byte. It says nothing about which parts of that
authority this repository actually speaks, so a module can call an endpoint the
authority never defined -- or keep calling a superseded one -- without any gate
noticing.

This validator closes that gap from both directions:

* every telephony endpoint and command/event family named in Odoo source must be
  declared in config/calling-contract-usage.json;
* every canonical declaration must exist in the pinned contract, and every
  legacy declaration must be absent from it and carry a reason plus a tracking
  reference, so divergence stays reviewed debt instead of silent drift.

The contract is YAML, but the source-head CI job installs no third-party
packages, so this reads it with the standard library only. That is sound here
because the bytes are already digest-pinned by the lock: the structural scan
below can only ever see the reviewed authority.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / ".codestra/calling-contract.lock.json"
USAGE = ROOT / "config/calling-contract-usage.json"
VENDOR = ROOT / "contracts/vendor/calling-contract-authority"
CONTRACT_FILES = (
    "contracts/telephony/codestra-calling-api.v1.openapi.yaml",
    "contracts/telephony/codestra-calling-events.v1.asyncapi.yaml",
)
OPENAPI = CONTRACT_FILES[0]
SCANNED_ROOTS = ("custom-addons",)

SCHEMA_VERSION = "codestra.calling-contract-usage.v1"
CANONICAL_STATUSES = frozenset({"in_use", "planned"})
LEGACY_STATUS = "legacy_pending_migration"
ALL_STATUSES = CANONICAL_STATUSES | {LEGACY_STATUS}
MINIMUM_REASON = 40

# Endpoint prefixes this repository is allowed to reach at all. A literal under
# one of these prefixes is telephony surface and must be declared; anything else
# is out of scope for this gate.
ENDPOINT_PREFIXES = ("/v1/telephony/", "/api/v1/realtime/", "/internal/v1/")
ENDPOINT_LITERAL = re.compile(
    r"[\"'](/(?:v1/telephony|api/v1/realtime|internal/v1)[A-Za-z0-9/_{}.-]*)[\"']"
)
FAMILY_LITERAL = re.compile(r"telephony\.[a-z]+\.[a-z-]+\.v\d+")
TRACKING = re.compile(r"\A[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*\Z")


class UsageError(ValueError):
    """The declared telephony surface does not match source or authority."""


def reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise UsageError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json(text: str) -> object:
    return json.loads(text, object_pairs_hook=reject_duplicate_pairs)


def read_contract(relative: str) -> str:
    if VENDOR.is_symlink() or not VENDOR.is_dir():
        raise UsageError("calling contract vendor directory is missing or unsafe")
    path = VENDOR
    for part in Path(relative).parts:
        path /= part
        if path.is_symlink():
            raise UsageError(f"calling contract symlink is prohibited: {relative}")
    if not path.is_file():
        raise UsageError(f"calling contract component is missing: {relative}")
    return path.read_text(encoding="utf-8")


def contract_paths(text: str) -> frozenset[str]:
    """Collect the path keys declared under the OpenAPI top-level `paths:`."""
    paths: set[str] = set()
    inside = False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line[:1].isspace():
            inside = line.rstrip() == "paths:"
            continue
        if not inside:
            continue
        match = re.fullmatch(r"  (/[A-Za-z0-9/_{}.-]*):", line.rstrip())
        if match:
            paths.add(match.group(1))
    if not paths:
        raise UsageError("calling contract declares no paths")
    return frozenset(paths)


def contract_families(texts: dict[str, str]) -> frozenset[str]:
    families: set[str] = set()
    for text in texts.values():
        families.update(FAMILY_LITERAL.findall(text))
    if not families:
        raise UsageError("calling contract declares no command or event families")
    return frozenset(families)


def scan_source() -> tuple[frozenset[str], frozenset[str]]:
    """Collect telephony endpoint and family literals named in Odoo source."""
    endpoints: set[str] = set()
    families: set[str] = set()
    for root in SCANNED_ROOTS:
        base = ROOT / root
        if not base.is_dir():
            raise UsageError(f"scanned root is missing: {root}")
        for path in sorted(base.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            if path.suffix not in {".py", ".xml", ".js", ".json"}:
                continue
            text = path.read_text(encoding="utf-8", errors="strict")
            endpoints.update(ENDPOINT_LITERAL.findall(text))
            families.update(FAMILY_LITERAL.findall(text))
    return frozenset(endpoints), frozenset(families)


def _entries(document: dict[str, object], key: str, field: str) -> dict[str, dict]:
    raw = document.get(key)
    if not isinstance(raw, list) or not raw:
        raise UsageError(f"{key} must be a non-empty list")
    entries: dict[str, dict] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise UsageError(f"{key} entries must be objects")
        allowed = {field, "status", "reason", "tracking"}
        if not set(entry) <= allowed or not {field, "status", "reason"} <= set(entry):
            raise UsageError(f"{key} entry fields are not canonical")
        name = entry[field]
        status = entry["status"]
        reason = entry["reason"]
        if not isinstance(name, str) or not name:
            raise UsageError(f"{key} entry {field} must be a non-empty string")
        if name in entries:
            raise UsageError(f"duplicate {key} entry: {name}")
        if status not in ALL_STATUSES:
            raise UsageError(f"{key} entry {name} has unsupported status {status!r}")
        if not isinstance(reason, str) or len(reason.strip()) < MINIMUM_REASON:
            raise UsageError(f"{key} entry {name} requires a specific reason")
        tracking = entry.get("tracking")
        if status == LEGACY_STATUS:
            if not isinstance(tracking, str) or not TRACKING.fullmatch(tracking):
                raise UsageError(
                    f"{key} entry {name} is legacy and requires an owner/repo#number "
                    "tracking reference"
                )
        elif tracking is not None:
            raise UsageError(f"{key} entry {name} may not carry a tracking reference")
        entries[name] = entry
    return entries


def validate(
    document: object,
    paths: frozenset[str],
    families: frozenset[str],
    lock: dict[str, object],
    source_endpoints: frozenset[str],
    source_families: frozenset[str],
) -> None:
    if not isinstance(document, dict):
        raise UsageError("calling contract usage must be a JSON object")
    expected = {
        "schema_version",
        "contract_version",
        "contract_sha256",
        "policy",
        "endpoints",
        "command_families",
        "event_families",
    }
    if set(document) != expected:
        raise UsageError("calling contract usage fields do not match the schema")
    if document["schema_version"] != SCHEMA_VERSION:
        raise UsageError("calling contract usage schema version is not canonical")
    if not isinstance(document["policy"], str) or len(document["policy"].strip()) < 80:
        raise UsageError("calling contract usage requires a stated policy")

    # Bind this declaration to the exact pinned authority. If the lock moves, the
    # declared surface must be re-reviewed against the new contract.
    for field, locked in (("contract_version", "version"), ("contract_sha256", "sha256")):
        if document[field] != lock.get(locked):
            raise UsageError(
                f"calling contract usage {field} does not match the pinned lock"
            )

    endpoints = _entries(document, "endpoints", "path")
    commands = _entries(document, "command_families", "name")
    events = _entries(document, "event_families", "name")

    for path, entry in endpoints.items():
        if not path.startswith(ENDPOINT_PREFIXES):
            raise UsageError(f"declared endpoint is outside telephony scope: {path}")
        present = path in paths
        if entry["status"] in CANONICAL_STATUSES and not present:
            raise UsageError(
                f"declared endpoint is absent from the pinned contract: {path}"
            )
        if entry["status"] == LEGACY_STATUS and present:
            raise UsageError(
                f"endpoint {path} exists in the pinned contract and is not legacy"
            )

    for label, declared in (("command", commands), ("event", events)):
        for name, entry in declared.items():
            present = name in families
            if entry["status"] in CANONICAL_STATUSES and not present:
                raise UsageError(
                    f"declared {label} family is absent from the pinned contract: {name}"
                )
            if entry["status"] == LEGACY_STATUS and present:
                raise UsageError(
                    f"{label} family {name} exists in the pinned contract and is not legacy"
                )

    # Source must not reach anything undeclared.
    for path in sorted(source_endpoints):
        if path not in endpoints:
            raise UsageError(f"source names an undeclared telephony endpoint: {path}")
    declared_families = set(commands) | set(events)
    for name in sorted(source_families):
        if name not in declared_families:
            raise UsageError(f"source names an undeclared telephony family: {name}")

    # A declaration that claims current use must be backed by source, so stale
    # claims cannot outlive the code that justified them.
    for path, entry in endpoints.items():
        if entry["status"] in {"in_use", LEGACY_STATUS} and path not in source_endpoints:
            raise UsageError(f"declared endpoint {path} is not used by any source file")
    for label, declared in (("command", commands), ("event", events)):
        for name, entry in declared.items():
            if entry["status"] == "in_use" and name not in source_families:
                raise UsageError(
                    f"declared {label} family {name} is not used by any source file"
                )


def load() -> tuple[object, frozenset[str], frozenset[str], dict[str, object]]:
    texts = {name: read_contract(name) for name in CONTRACT_FILES}
    lock = parse_json(LOCK.read_text(encoding="utf-8"))
    if not isinstance(lock, dict):
        raise UsageError("calling contract lock must be a JSON object")
    return (
        parse_json(USAGE.read_text(encoding="utf-8")),
        contract_paths(texts[OPENAPI]),
        contract_families(texts),
        lock,
    )


def self_test() -> None:
    """Prove each rule actually rejects, so the gate cannot silently pass."""
    document, paths, families, lock = load()
    source_endpoints, source_families = scan_source()
    validate(document, paths, families, lock, source_endpoints, source_families)

    def rejects(mutate, message: str) -> None:
        broken = json.loads(json.dumps(document))
        args = mutate(broken)
        try:
            validate(*args) if args else validate(
                broken, paths, families, lock, source_endpoints, source_families
            )
        except UsageError:
            return
        raise UsageError(f"usage validation failed to reject: {message}")

    def drop_field(doc):
        del doc["policy"]

    def wrong_digest(doc):
        doc["contract_sha256"] = "0" * 64

    def unknown_status(doc):
        doc["endpoints"][0]["status"] = "whatever"

    def legacy_without_tracking(doc):
        for entry in doc["endpoints"]:
            entry.pop("tracking", None)
            entry["status"] = LEGACY_STATUS

    def canonical_absent_from_contract(doc):
        doc["endpoints"].append(
            {
                "path": "/v1/telephony/not-in-the-authority",
                "status": "in_use",
                "reason": "A canonical claim for a route the authority never defines.",
            }
        )

    def legacy_that_is_actually_canonical(doc):
        doc["endpoints"].append(
            {
                "path": "/v1/telephony/commands",
                "status": LEGACY_STATUS,
                "reason": "Claiming the canonical command envelope is legacy debt.",
                "tracking": "appolon1908-hue/Odoo#75",
            }
        )

    def duplicate_entry(doc):
        doc["command_families"].append(dict(doc["command_families"][0]))

    for mutate, label in (
        (drop_field, "a missing top-level field"),
        (wrong_digest, "a lock digest mismatch"),
        (unknown_status, "an unsupported status"),
        (legacy_without_tracking, "legacy debt with no tracking reference"),
        (canonical_absent_from_contract, "a canonical route absent from the authority"),
        (legacy_that_is_actually_canonical, "legacy debt that the authority defines"),
        (duplicate_entry, "a duplicate declaration"),
    ):
        rejects(lambda doc, m=mutate: (m(doc), None)[1], label)

    # An undeclared literal in source must fail even when the declaration is valid.
    try:
        validate(
            document,
            paths,
            families,
            lock,
            source_endpoints | {"/v1/telephony/undeclared"},
            source_families,
        )
    except UsageError:
        pass
    else:
        raise UsageError("usage validation failed to reject an undeclared endpoint")

    try:
        validate(
            document,
            paths,
            families,
            lock,
            source_endpoints,
            source_families | {"telephony.call.undeclared.v1"},
        )
    except UsageError:
        pass
    else:
        raise UsageError("usage validation failed to reject an undeclared family")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        document, paths, families, lock = load()
        source_endpoints, source_families = scan_source()
        validate(document, paths, families, lock, source_endpoints, source_families)
        print(f"CALLING_CONTRACT_ENDPOINTS={len(paths)}")
        print(f"CALLING_CONTRACT_FAMILIES={len(families)}")
        print(f"ODOO_TELEPHONY_ENDPOINTS_IN_SOURCE={len(source_endpoints)}")
    print("CALLING_CONTRACT_USAGE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
