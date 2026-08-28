import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = ROOT / "schemas" / "lead-automation"
source = json.loads((ROOT / "schemas" / "MIDDLEWARE-CONTRACT-SOURCE.json").read_text())
manifest_path = SCHEMAS / "SHA256SUMS.json"
manifest = json.loads(manifest_path.read_text())
assert source["source_repository"] == "Codestra-SRL/codestra-middleware"
assert source["source_pr"] == 65
assert source["source_head"] == "04fa56f4c8bb8caea3e5281816a2986bcb47ba05"
assert source["hmac_contract"] == "HMAC-V2"
assert source["hmac_scope"] == "lead-automation.odoo-apply.write"
assert source["schema_manifest_sha256"] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
assert source["contract_version"] == "1.1"
assert source["coordinated_extension_repository"] == "Codestra-SRL/codestra-middleware"
assert source["coordinated_extension_pr"] == 68
assert manifest["contract_version"] == "1.1" and manifest["schema_count"] == 14
for name, digest in manifest["schemas"].items():
    assert hashlib.sha256((SCHEMAS / name).read_bytes()).hexdigest() == digest
apply = json.loads((SCHEMAS / "lead-odoo-apply-v1.json").read_text())
ack = json.loads((SCHEMAS / "lead-odoo-ack-v1.json").read_text())
assert apply["additionalProperties"] is False and len(apply["allOf"]) == 8
assert ack["properties"]["result"]["enum"] == [
    "APPLIED", "NO_CHANGE", "DENIED", "CONSENT_BLOCKED", "DNC_BLOCKED",
    "QUARANTINED", "FAILED",
]
print("MIDDLEWARE_CONTRACT_PIN_GATE=PASS")
