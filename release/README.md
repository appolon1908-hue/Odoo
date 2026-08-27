# Contact-center release candidate

The manual workflow packages source evidence only. It validates the exact selected branch head, builds a deterministic Git archive, generates a source-addon SPDX SBOM, writes a blocked-by-default final report, creates a manifest, computes checksums, and uploads a short-lived GitHub Actions artifact.

It does not sign commits, build or push a container image, publish a GitHub release, modify a server, install modules, migrate a database, activate a provider, or deploy production. Those gates remain explicit blockers.
