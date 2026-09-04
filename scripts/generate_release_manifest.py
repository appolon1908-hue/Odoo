#!/usr/bin/env python3
"""Generate deterministic source evidence for the signed OCI candidate workflow."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def command(*args: str) -> str:
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def created_at() -> str:
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
    parser.add_argument("--source-archive", required=True)
    parser.add_argument("--sbom", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    source_sha = command("git", "rev-parse", "HEAD")
    source_verified = os.environ.get("SOURCE_COMMIT_VERIFIED", "false").lower() == "true"
    files = [ROOT / args.source_archive, ROOT / args.sbom, ROOT / args.report]
    for path in files:
        if not path.is_file():
            raise FileNotFoundError(path)

    safety = json.loads(
        (ROOT / "config" / "mission-safety-policy.json").read_text(encoding="utf-8")
    )
    satisfied = [
        "deterministic-source-archive",
        "source-addon-spdx-sbom",
        "checksummed-release-metadata",
        "blocked-by-default-report",
        "all-live-capabilities-false",
    ]
    blocked = [
        "immutable-container-image-digest",
        "complete-container-sbom",
        "container-vulnerability-and-secret-evidence",
        "signed-slsa-provenance",
        "signed-sbom-attestation",
        "production-source-authority-reconciliation",
        "current-paired-database-filestore-backup",
        "isolated-staging-certification",
        "representative-restore",
        "rollback-rehearsal",
        "production-read-only-canary",
        "bounded-production-soak",
        "production-activation-approval",
    ]
    if source_verified:
        satisfied.insert(0, "signed-protected-main-commit")
    else:
        blocked.insert(0, "signed-protected-main-commit")

    payload = {
        "schema_version": 2,
        "release_type": "source-evidence-for-signed-oci-production-candidate",
        "source_repository": "appolon1908-hue/Odoo",
        "source_sha": source_sha,
        "source_tree": command("git", "rev-parse", "HEAD^{tree}"),
        "source_commit_verified_signature": source_verified,
        "created_at": created_at(),
        "artifact_ready": False,
        "production_ready": False,
        "runtime_changed": False,
        "live_capabilities": safety["live_capabilities"],
        "artifacts": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": digest(path),
                "bytes": path.stat().st_size,
            }
            for path in files
        ],
        "satisfied_source_gates": satisfied,
        "blocked_gates": blocked,
        "next_gate": "build-scan-publish-and-attest-immutable-oci-image",
    }

    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"RELEASE_MANIFEST_PATH={output.relative_to(ROOT)}")
    print(f"SOURCE_COMMIT_VERIFIED={'true' if source_verified else 'false'}")
    print("SOURCE_EVIDENCE_PRODUCTION_READY=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
