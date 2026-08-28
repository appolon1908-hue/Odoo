# Isolated staging certification

## Entry gates

- All stacked PRs merged in dependency order through protected controls.
- Exact final protected SHA independently approved.
- Immutable add-on or container artifact identified by digest and verified.
- Complete SBOM, vulnerability scan, secret scan, provenance, and checksums available.
- Encrypted backup and isolated restore pass.
- Effective runtime layout and rollback target audited.
- All live capability flags false.

## Certification sequence

1. Restore a sanitized database into an isolated environment.
2. Install or upgrade the exact selected modules.
3. Reconcile counts, external IDs, customer links, call links, contracts, consent, and audit records.
4. Interrupt and restart one reviewed migration path.
5. Verify Keycloak issuer, audiences, scopes, service-account non-interactive policy, and session behavior.
6. Verify Kong route mapping, mTLS, rate limits, request IDs, correlation IDs, and safe errors.
7. Run exact replay, altered-body replay, out-of-order events, worker restart, stale lease, retry, dead-letter, and reconciliation tests.
8. Run the ten negative-authorization scenarios.
9. Run browser screen-pop, refresh recovery, mandatory wrap-up, keyboard, accessibility, and supported display tests.
10. Run 150 synthetic agent sessions and 50 events per second for five minutes.
11. Verify backup restoration and the documented rollback.
12. Complete the required soak with no external delivery.

Any failed or missing item is `BLOCKED`, never forced to `PASS`.
