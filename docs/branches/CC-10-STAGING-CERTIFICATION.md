# CC-10 — Release Candidate and Staging Certification Boundary

This branch adds manual, exact-SHA source-candidate packaging and the staging, production-gate, migration, and rollback runbooks.

## Candidate contents

- deterministic source archive;
- source-addon SPDX SBOM with an explicit incomplete-container warning;
- release manifest and artifact hashes;
- SHA-256 checksums;
- a final report that defaults every unproven runtime or release gate to `BLOCKED`.

## Explicit non-actions

The workflow cannot run on push or pull request, uses read-only repository permission, persists no checkout credentials, pins every action by commit SHA, and has no release, registry, Docker, SSH, Compose, Kubernetes, rsync, database, or deployment command. It uploads evidence only.

No live server, database, campaign, provider, callback, n8n workflow, VICIdial control, or PSTN capability is changed.
