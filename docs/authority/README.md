# Odoo 19 contact-center authority packet

This directory records the user-supplied contact-center authority and the
controlled inputs available for staging implementation. It does not authorize a
production deployment or live integration activity.

## Canonical authority

- Document: `ODOO_19_TOP_TIER_CALL_CENTER_CAMPAIGN_ISOLATION_SPEC.md`
- Source: user-provided complete architecture and Codex implementation authority
- Source SHA-256: `ad5257a49e4028d832342537226ffc0d2514dd74bca3bb63d4bc786be31fdc0e`
- Repository Git blob: `eb5e48e0c6409e8cadd46922a02438362ee61633`
- Size: 73,531 bytes / 1,405 lines
- Status: `COMPLETE`
- Release posture: `STAGING-ONLY`

The repository copy is byte-identical to the user-supplied file. It supersedes
`ODOO_19_CONTACT_CENTER_AUTHORITY.md` as the governing Odoo campaign-isolation,
membership, workspace, security, integration, test, and production-gate
authority. The superseded partial source remains unchanged for provenance and
audit history.

The canonical authority keeps live dialing, live lead publication, production
agent synchronization, external email delivery, provisioning, IVR activation,
callbacks, recording playback, and production activation disabled until its
formal gates and separate human approvals pass.

## Provenance and controlled-input status

| Artifact | Source | SHA-256 / verification | Status |
| --- | --- | --- | --- |
| `ODOO_19_TOP_TIER_CALL_CENTER_CAMPAIGN_ISOLATION_SPEC.md` | Complete user-provided authority | SHA-256 `ad5257a49e4028d832342537226ffc0d2514dd74bca3bb63d4bc786be31fdc0e`; Git blob `eb5e48e0c6409e8cadd46922a02438362ee61633`; byte-identical | COMPLETE |
| `ODOO_19_CONTACT_CENTER_AUTHORITY.md` | Earlier user attachment `5eff6e6f-dfb2-4903-9d48-b70f22bcea9c/pasted-text.txt` | Source SHA-256 `4A55B54B4C16FDE929E648500730E6A01A5A5FBA701619ED493AFD2DC9118320`; repository copy is byte-different only because of the final newline and is equal after newline normalization | SUPERSEDED-PARTIAL |
| `odoo_vicidial_campaign_identifier_matrix.csv` | The 93 canonical/native identifier pairs embedded in the authority | 93 unique canonical codes; 93 unique VICIdial IDs; all native IDs are at most eight characters | PARTIAL |
| `odoo_campaign_access_control_matrix.csv` | Section 6 of the authority | Ten role definitions transcribed into a machine-readable matrix | PARTIAL |
| `odoo_campaign_disposition_catalog.csv` | Referenced by the canonical authority | Not supplied or found in the repository or attachment set | MISSING |
| `VICIDIAL_ODOO_MAPPING_SPEC.md` | `codestra-production-platform` commit `f3a16308194378a7b1580e04943dc98d64619077` | SHA-256 `A2E0B26F52F63961ED0151C5C750B069049A436967A9970BB8FD7698AC3C24D9` | PARTIAL |

The superseded partial attachment ends mid-sentence with `Compliance must be
reviewed by qualified`. It is retained exactly after newline normalization and
must not be used to override or truncate the canonical complete authority.

Adding the complete authority does not automatically promote the related CSV,
mapping, mission, implementation, runtime, or evidence artifacts to `PASS`.
Each artifact keeps its independently verified status until configuration,
functional testing, read-back, and retained evidence exist.

## Controlled-input rules

- The identifier matrix is not seed-ready. It records exact campaign identifiers,
  business units, direction, and callback compatibility, but fields that the
  authority did not provide are explicitly `MISSING` and the rows are `PARTIAL`.
- The unavailable 2,677-row disposition catalog must not be reconstructed from
  examples. No disposition import, destructive reconciliation, or production
  provisioning may use an invented substitute.
- The access matrix is an architectural control catalog. A role row becomes
  `PASS` only after groups, membership rules, functional negative tests, read-back,
  and retained evidence all exist.
- Existing hash-like VICIdial identifiers are not silently renamed. Migration is a
  separately approved, reversible, disabled-state operation with collision checks
  and read-back.
- All production and delivery flags remain false. This packet's recommendation is
  `STAGING-ONLY` and its production state is `PRODUCTION_BLOCKED`.

## Authority precedence

For Odoo campaign isolation, membership, workspace behavior, authorization,
email isolation, telephony mappings, scripts, dispositions, callbacks,
recordings, quality, workforce, compliance, reporting, tests, and production
gates, `ODOO_19_TOP_TIER_CALL_CENTER_CAMPAIGN_ISOLATION_SPEC.md` controls.

The cross-system mapping specification remains a preserved baseline for campaign
inventory and system trust boundaries. Any conflict is documented and resolved
through an ADR; it is never silently applied. The complete authority does not
authorize deployment, credential mutation, runtime activation, or production
traffic.