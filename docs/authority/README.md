# Odoo 19 contact-center authority packet

This directory records the user-supplied contact-center authority and the
controlled inputs available for staging implementation. It does not authorize a
production deployment or live integration activity.

## Provenance

| Artifact | Source | SHA-256 / verification | Status |
| --- | --- | --- | --- |
| `ODOO_19_CONTACT_CENTER_AUTHORITY.md` | User attachment `5eff6e6f-dfb2-4903-9d48-b70f22bcea9c/pasted-text.txt` | Source SHA-256 `4A55B54B4C16FDE929E648500730E6A01A5A5FBA701619ED493AFD2DC9118320`; repository copy is byte-different only because of the final newline and is equal after newline normalization | PARTIAL |
| `odoo_vicidial_campaign_identifier_matrix.csv` | The 93 canonical/native identifier pairs embedded in the authority | 93 unique canonical codes; 93 unique VICIdial IDs; all native IDs are at most eight characters | PARTIAL |
| `odoo_campaign_access_control_matrix.csv` | Section 6 of the authority | Ten role definitions transcribed into a machine-readable matrix | PARTIAL |
| `odoo_campaign_disposition_catalog.csv` | Referenced by section 15.7 of the authority | Not supplied or found in the repository or attachment set | MISSING |
| `VICIDIAL_ODOO_MAPPING_SPEC.md` | `codestra-production-platform` commit `f3a16308194378a7b1580e04943dc98d64619077` | SHA-256 `A2E0B26F52F63961ED0151C5C750B069049A436967A9970BB8FD7698AC3C24D9` | PARTIAL |

The user attachment ends mid-sentence with `Compliance must be reviewed by
qualified`. The repository copy preserves that source exactly after newline
normalization. A complete replacement authority should supersede this copy when
available.

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

For Odoo campaign isolation, membership, and workspace behavior, the user-supplied
authority in this directory controls. The cross-system mapping specification is a
preserved baseline for the campaign inventory and system trust boundaries. Any
conflict is documented and resolved through an ADR; it is never silently applied.
