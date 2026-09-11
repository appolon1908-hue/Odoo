# Codestra VICIdial Recording Reference

Metadata-only VICIdial call-recording references and scoped playback. This
module never stores or streams recording audio itself — it holds a reviewed
`codestra.vicidial.recording` reference row per call, scoped by a recording
scope group, and exposes playback through the existing
`codestra_vicidial_crm` agent/campaign boundary.

## Implemented

- `codestra.vicidial.recording`: one reference row per recorded call, with a
  SHA-256 integrity field, a non-negative file-size constraint, and a
  reviewed partial unique index enforcing at most one row per object version.
- `codestra.vicidial.recording.scope.group`: scopes which agents/campaigns a
  recording reference is visible to.
- `controllers/service_auth.py`: HMAC-signed service-identity authentication
  (timestamp/nonce/content-hash/idempotency-key) for the recording ingest
  API, exercised by `tests/test_service_auth_source.py`.

## Boundaries

- Depends on `codestra_vicidial_crm` for the agent/campaign identity this
  module scopes recordings against; it does not write to that addon's
  models.
- No raw SQL beyond one reviewed schema-index creation in
  `models/recording.py` (`_auto_init`); see
  `config/canonical-addon-baseline.json`'s `integration_boundary_exceptions`
  for this addon.
