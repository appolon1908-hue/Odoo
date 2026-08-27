#!/usr/bin/env python3
"""Generate release-candidate metadata and explicit unsatisfied gates."""

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
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH") or command("git", "show", "-s", "--format=%ct", "HEAD"))
    return dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-archive", required=True)
    parser.add_argument("--sbom", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source_sha = command("git", "rev-parse", "HEAD")
    files = [ROOT / args.source_archive, ROOT / args.sbom, ROOT / args.report]
    for path in files:
        if not path.is_file():
            raise FileNotFoundError(path)
    safety = json.loads((ROOT / "config/mission-safety-policy.json").read_text(encoding="utf-8"))
    payload = {
        "schema_version": 1,
        "release_type": "source-candidate-only",
        "source_repository": "appolon1908-hue/Odoo",
        "source_sha": source_sha,
        "source_tree": command("git", "rev-parse", "HEAD^{tree}"),
        "source_commit_verified_signature": False,
        "created_at": created_at(),
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
        "satisfied_source_gates": [
            "deterministic-source-archive",
            "source-addon-spdx-sbom",
            "checksummed-release-metadata",
            "blocked-by-default-report",
            "all-live-capabilities-false",
        ],
        "blocked_gates": [
            "signed-protected-merge-commit",
            "immutable-container-image-digest",
            "complete-container-sbom",
            "vulnerability-and-secret-scan-evidence",
            "provenance-and-signature",
            "database-migration-and-restore",
            "isolated-staging-certification",
            "rollback-rehearsal",
            "bounded-canary-and-soaks",
            "production-approval",
        ],
    }
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"RELEASE_MANIFEST_PATH={output.relative_to(ROOT)}")
    print("SOURCE_CANDIDATE_PRODUCTION_READY=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
