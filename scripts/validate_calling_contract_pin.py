#!/usr/bin/env python3
"""Validate the pinned Codestra calling contract without enabling effects."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / ".codestra/calling-contract.lock.json"
VENDOR = ROOT / "contracts/vendor/calling-contract-authority"
SOURCE_FILE = "calling-contract-authority.source.json"
SOURCE_COMMIT = "21e985a67d1656c840fa9629d68b917adcf5d7da"
COMPONENT_PATHS = (
    "contracts/telephony/codestra-calling-api.v1.openapi.yaml",
    "contracts/telephony/codestra-calling-ecosystem.v1.yaml",
    "contracts/telephony/codestra-calling-events.v1.asyncapi.yaml",
    "schemas/integration-event-envelope-v1.schema.json",
)
EXPECTED = {
    "schema_version": "codestra.calling-contract-lock.v1",
    "version": "1.0.0",
    "sha256": "b39cdffe56a8185c91174228f0423df68b1137f34875f6ee52f9914f904bf724",
    "authority": "appolon1908-hue/codestra-production-platform#257",
    "role": "agent_workspace",
    "external_effects_enabled": False,
}


def reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def parse_json(text: str) -> object:
    return json.loads(text, object_pairs_hook=reject_duplicate_pairs)


def read_component(root: Path, relative: str) -> bytes:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("calling contract vendor directory is missing or unsafe")
    path = root
    for part in Path(relative).parts:
        path /= part
        if path.is_symlink():
            raise ValueError(f"calling contract symlink is prohibited: {relative}")
    if not path.is_file():
        raise ValueError(f"calling contract component is missing: {relative}")
    return path.read_bytes()


def compute_authority_digest(vendor_dir: Path = VENDOR) -> str:
    source = parse_json(read_component(vendor_dir, SOURCE_FILE).decode("utf-8"))
    identity = {
        "schema_version": "codestra.calling-contract-source.v1",
        "repository": "appolon1908-hue/codestra-production-platform",
        "commit": SOURCE_COMMIT,
        "version": EXPECTED["version"],
        "authority": EXPECTED["authority"],
        "sha256": EXPECTED["sha256"],
    }
    if not isinstance(source, dict) or set(source) != {*identity, "components"}:
        raise ValueError("calling contract source fields do not match the schema")
    if any(source[key] != value for key, value in identity.items()):
        raise ValueError("calling contract source identity does not match authority")
    components = source["components"]
    if not isinstance(components, list) or len(components) != len(COMPONENT_PATHS):
        raise ValueError("calling contract component inventory is incomplete")
    lines = []
    for relative, component in zip(COMPONENT_PATHS, components):
        if (
            not isinstance(component, dict)
            or set(component) != {"path", "sha256"}
            or component["path"] != relative
        ):
            raise ValueError("calling contract component paths or ordering changed")
        actual = hashlib.sha256(read_component(vendor_dir, relative)).hexdigest()
        if component["sha256"] != actual:
            raise ValueError(f"calling contract component digest mismatch: {relative}")
        # Match the authority's telephony-contract-digest.sh: hash the ordered
        # sha256sum output, including two spaces, original paths and newlines.
        lines.append(f"{actual}  {relative}\n")
    digest = hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()
    if digest != source["sha256"]:
        raise ValueError("calling contract bytes do not match the pinned digest")
    return digest


def validate(document: object, vendor_dir: Path = VENDOR) -> None:
    if not isinstance(document, dict):
        raise ValueError("calling contract lock must be a JSON object")
    if set(document) != set(EXPECTED):
        raise ValueError("calling contract lock fields do not match the canonical schema")
    for field in ("schema_version", "version", "sha256", "authority", "role"):
        if not isinstance(document.get(field), str) or document[field] != EXPECTED[field]:
            raise ValueError(f"calling contract {field} does not match authority")
    if not re.fullmatch(r"[0-9a-f]{64}", document["sha256"]):
        raise ValueError("calling contract digest is malformed")
    if type(document.get("external_effects_enabled")) is not bool:
        raise ValueError("external_effects_enabled must be a JSON boolean")
    if document["external_effects_enabled"] is not False:
        raise ValueError("calling contract must remain fail closed")
    if compute_authority_digest(vendor_dir) != document["sha256"]:
        raise ValueError("calling contract lock does not match authority bytes")


def load() -> object:
    return parse_json(LOCK.read_text(encoding="utf-8"))


def self_test() -> None:
    validate(copy.deepcopy(EXPECTED))
    invalid: list[object] = [
        None,
        [],
        {**EXPECTED, "external_effects_enabled": "false"},
        {**EXPECTED, "external_effects_enabled": "true"},
        {**EXPECTED, "external_effects_enabled": 0},
        {**EXPECTED, "external_effects_enabled": None},
        {**EXPECTED, "external_effects_enabled": True},
        {key: value for key, value in EXPECTED.items() if key != "authority"},
        {**EXPECTED, "authority": "wrong/repository#1"},
        {**EXPECTED, "role": "wrong_role"},
        {**EXPECTED, "sha256": "0" * 64},
        {**EXPECTED, "unexpected": "field"},
    ]
    for number, document in enumerate(invalid, 1):
        try:
            validate(document)
        except ValueError:
            continue
        raise AssertionError(f"negative calling-contract fixture {number} was accepted")

    for field in ("sha256", "external_effects_enabled"):
        text = json.dumps(EXPECTED)
        duplicate = text[:-1] + f', "{field}": ' + json.dumps(EXPECTED[field]) + "}"
        try:
            parse_json(duplicate)
        except ValueError:
            pass
        else:
            raise AssertionError(f"duplicate lock field was accepted: {field}")

    # Mutate disposable copies, never the checked-out authority files.
    for mutation in (
        "tampered", "missing", "symlink", "ancestor_symlink", "missing_source",
        "wrong_commit", "reordered", "traversal", "duplicate_component",
        "duplicate_source_key", "changed_file_and_checksum",
    ):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "authority"
            shutil.copytree(VENDOR, fixture)
            component = fixture / COMPONENT_PATHS[0]
            source_path = fixture / SOURCE_FILE
            source = parse_json(source_path.read_text(encoding="utf-8"))
            if mutation == "tampered":
                component.write_bytes(component.read_bytes() + b"\n# tampered\n")
            elif mutation == "missing":
                component.unlink()
            elif mutation == "symlink":
                component.unlink()
                component.symlink_to(VENDOR / COMPONENT_PATHS[0])
            elif mutation == "ancestor_symlink":
                shutil.rmtree(fixture / "contracts")
                (fixture / "contracts").symlink_to(VENDOR / "contracts", target_is_directory=True)
            elif mutation == "missing_source":
                source_path.unlink()
            elif mutation == "duplicate_source_key":
                source_path.write_text(
                    json.dumps(source)[:-1] + ', "commit": "' + SOURCE_COMMIT + '"}',
                    encoding="utf-8",
                )
            else:
                if mutation == "wrong_commit":
                    source["commit"] = "0" * 40
                elif mutation == "reordered":
                    source["components"].reverse()
                elif mutation == "traversal":
                    source["components"][0]["path"] = "../outside.yaml"
                elif mutation == "duplicate_component":
                    source["components"][1] = source["components"][0]
                elif mutation == "changed_file_and_checksum":
                    component.write_bytes(component.read_bytes() + b"\n# tampered\n")
                    source["components"][0]["sha256"] = hashlib.sha256(component.read_bytes()).hexdigest()
                source_path.write_text(json.dumps(source), encoding="utf-8")
            try:
                validate(copy.deepcopy(EXPECTED), fixture)
            except ValueError:
                continue
            raise AssertionError(f"calling-contract mutation was accepted: {mutation}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        validate(load())
    print("CALLING_CONTRACT_PIN=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
