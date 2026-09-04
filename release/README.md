# Codestra Odoo production candidate

The canonical manual workflow is `.github/workflows/cc-release-candidate.yml`. It may run only from an exact, GitHub-verified `main` commit and requires the explicit confirmation `BUILD_SIGNED_PRODUCTION_CANDIDATE`.

The workflow:

1. validates the exact signed source SHA;
2. runs the complete source gate;
3. builds deterministic source evidence;
4. builds the production image from the reviewed digest-pinned Odoo 19 base;
5. rejects symbolic links and verifies the non-root Odoo runtime identity;
6. blocks embedded secrets and fixed critical vulnerabilities;
7. retains complete high/critical vulnerability evidence;
8. creates a complete container SPDX SBOM;
9. refuses to replace an existing SHA tag;
10. publishes `ghcr.io/appolon1908-hue/odoo:sha-<source-sha>`;
11. resolves the immutable registry digest;
12. creates signed SLSA provenance and SBOM attestations through GitHub Actions OIDC and Sigstore;
13. creates a production-candidate manifest and verified SHA-256 evidence bundle.

Runtime manifests must consume the digest reference:

```text
ghcr.io/appolon1908-hue/odoo@sha256:<digest>
```

The SHA tag is informational and immutable. `latest` is prohibited.

Candidate publication does **not** modify a server, install or upgrade an Odoo module, migrate a database, restore a filestore, activate a provider, or deploy production. Those gates remain blocked until a release-specific copy of `production-evidence-template.json` validates through `scripts/validate_production_evidence.py`.

Required runtime order:

```text
source authority
  -> current paired backup
  -> isolated staging upgrade/restart
  -> Caddy -> Kong -> Middleware -> Odoo certification
  -> representative paired restore
  -> rollback rehearsal
  -> production read-only canary
  -> bounded soak
  -> explicit capability activation
```

Every live capability defaults false. A signed image is an artifact candidate, not production authorization.
