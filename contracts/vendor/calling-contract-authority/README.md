# Pinned calling-contract authority

These four contract components are copied without content changes from
`appolon1908-hue/codestra-production-platform` commit
`21e985a67d1656c840fa9629d68b917adcf5d7da`, the authority for calling-contract
version `1.0.0` and issue #257. Original relative paths are retained so the
OpenAPI document's `../../schemas/integration-event-envelope-v1.schema.json`
reference resolves locally.

`calling-contract-authority.source.json` records the exact source identity and
component hashes. `scripts/validate_calling_contract_pin.py` validates that
identity, hashes every component, and reproduces the source repository's
`scripts/telephony-contract-digest.sh` algorithm. The aggregate digest must match
both this provenance record and `.codestra/calling-contract.lock.json`.

Run from the repository root:

```sh
python3 scripts/validate_calling_contract_pin.py
python3 scripts/validate_calling_contract_pin.py --self-test
```

The tests use temporary copies to reject tampered or missing files, symlinks,
changed source identities, reordered or duplicate components, path traversal,
duplicate JSON keys, and changes to both a file and its declared checksum.
Source CI and the dedicated pin workflow cover vendor-only changes.

Changing this pin requires a reviewed platform contract revision and matching
lock, source identity, component inventory, hashes, and validator expectations.
This verifies Odoo's source contract dependency. It does not certify generated
SDK client parity, cross-service runtime behavior, or production activation.
