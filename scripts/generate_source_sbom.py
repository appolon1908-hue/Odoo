#!/usr/bin/env python3
"""Generate a deterministic SPDX source-addon SBOM for custom Odoo modules."""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDONS = ROOT / "custom-addons"
SAFE_ID = re.compile(r"[^A-Za-z0-9.-]+")
LICENSE_MAP = {
    "LGPL-3": "LGPL-3.0-only",
    "AGPL-3": "AGPL-3.0-only",
    "MIT": "MIT",
    "Apache-2.0": "Apache-2.0",
}


def command(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def spdx_id(value: str) -> str:
    return "SPDXRef-" + SAFE_ID.sub("-", value).strip("-")


def load_manifest(path: Path) -> dict:
    value = ast.literal_eval(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: manifest is not a dictionary")
    return value


def source_checksum(module: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in module.rglob("*") if item.is_file()):
        digest.update(path.relative_to(module).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def creation_time() -> str:
    epoch = int(
        os.environ.get("SOURCE_DATE_EPOCH")
        or command("git", "show", "-s", "--format=%ct", "HEAD")
    )
    return (
        dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source_sha = command("git", "rev-parse", "HEAD")
    created = creation_time()
    manifests = sorted(ADDONS.glob("*/__manifest__.py"))
    packages: list[dict] = []
    relationships: list[dict] = []
    custom_names = {path.parent.name for path in manifests}

    for manifest_path in manifests:
        module = manifest_path.parent
        manifest = load_manifest(manifest_path)
        package_id = spdx_id(f"Package-{module.name}")
        raw_license = str(manifest.get("license", "NOASSERTION"))
        declared_license = LICENSE_MAP.get(raw_license, "NOASSERTION")
        package = {
            "name": module.name,
            "SPDXID": package_id,
            "versionInfo": str(manifest.get("version", "UNKNOWN")),
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": declared_license,
            "copyrightText": "NOASSERTION",
            "supplier": "Organization: Codestra",
            "checksums": [
                {
                    "algorithm": "SHA256",
                    "checksumValue": source_checksum(module),
                }
            ],
            "externalRefs": [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": f"pkg:generic/odoo-addon/{module.name}@{manifest.get('version', 'UNKNOWN')}?odoo=19",
                }
            ],
            "annotations": [
                {
                    "annotationDate": created,
                    "annotationType": "OTHER",
                    "annotator": "Tool: Codestra source SBOM generator",
                    "comment": (
                        "Source-addon inventory only; this is not a complete container or "
                        f"operating-system SBOM. Odoo manifest license={raw_license}."
                    ),
                }
            ],
        }
        packages.append(package)
        relationships.append(
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": package_id,
            }
        )
        for dependency in manifest.get("depends", []):
            if dependency in custom_names:
                relationships.append(
                    {
                        "spdxElementId": package_id,
                        "relationshipType": "DEPENDS_ON",
                        "relatedSpdxElement": spdx_id(f"Package-{dependency}"),
                    }
                )

    namespace = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"https://github.com/appolon1908-hue/Odoo/commit/{source_sha}",
    )
    document = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"codestra-odoo-contact-center-source-{source_sha}",
        "documentNamespace": f"urn:uuid:{namespace}",
        "creationInfo": {
            "created": created,
            "creators": [
                "Organization: Codestra",
                "Tool: Codestra source SBOM generator",
            ],
            "comment": (
                "Source-addon SBOM. Complete image, Python, JavaScript, Odoo core, OS, "
                "and transitive dependency evidence remains required."
            ),
        },
        "documentDescribes": [item["SPDXID"] for item in packages],
        "packages": packages,
        "relationships": relationships,
        "annotations": [
            {
                "annotationDate": created,
                "annotationType": "OTHER",
                "annotator": "Tool: Codestra source SBOM generator",
                "comment": "PRODUCTION_SBOM_STATUS=BLOCKED_COMPLETE_IMAGE_SBOM_REQUIRED",
            }
        ],
    }
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"SOURCE_SBOM_PACKAGES={len(packages)}")
    print(f"SOURCE_SBOM_PATH={output.relative_to(ROOT)}")
    print("SOURCE_SBOM=PASS")
    print("COMPLETE_IMAGE_SBOM=BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
