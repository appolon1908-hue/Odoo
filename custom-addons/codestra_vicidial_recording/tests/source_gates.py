"""Source-only gates that run without an Odoo runtime."""

import ast
import csv
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise SystemExit(message)


manifest = ast.literal_eval((ROOT / "__manifest__.py").read_text())
require(
    manifest["depends"] == ["base", "web", "codestra_vicidial_crm"],
    "module dependencies drifted",
)
for path in ROOT.rglob("*.py"):
    ast.parse(path.read_text(), filename=str(path))
for path in ROOT.rglob("*.xml"):
    ElementTree.parse(path)
for path in ROOT.rglob("*.csv"):
    with path.open(newline="", encoding="utf-8") as stream:
        list(csv.reader(stream))

model = (ROOT / "models/recording.py").read_text()
controller = (ROOT / "controllers/recording_api.py").read_text()
service_auth = (ROOT / "controllers/service_auth.py").read_text()
javascript = (ROOT / "static/src/js/playback_action.js").read_text()
require("fields.Binary" not in model, "audio Binary field is prohibited")
for required_field in (
    "recording_uid",
    "contract_version",
    "campaign_key",
    "file_size_bytes",
    "sha256",
    "retention_class",
    "environment",
):
    require(
        required_field in model, f"required canonical field missing: {required_field}"
    )
require(
    "CHECK(contract_version = '1.0')" in model,
    "contract v1 database constraint missing",
)
require(
    "WHERE object_version_id IS NOT NULL" in model,
    "partial object-version uniqueness missing",
)
require("def _no_direct_recording_delete" in model, "direct deletion guard missing")
require(
    "codestra.vicidial.recording.retention.audit" in model, "retention audit missing"
)
require(
    'auth="none"' in controller and "def _authenticate" in controller,
    "service auth missing",
)
for header in (
    "X-Service-Identity",
    "X-Service-Audience",
    "X-Codestra-Timestamp",
    "X-Codestra-Nonce",
    "X-Codestra-Content-SHA256",
    "X-Codestra-Signature",
    "Idempotency-Key",
    "X-Codestra-Environment",
):
    require(header in service_auth, f"HMAC header missing: {header}")
require("hashlib.sha256" in service_auth, "HMAC SHA-256 contract missing")
require("hmac.compare_digest" in service_auth, "constant-time signature check missing")
for field in ("identity", "audience", "environment"):
    require(
        f"{field},"
        not in service_auth.split("def signing_material(", 1)[1].split("):", 1)[0],
        f"{field} must be authenticated as a header, not added to PR B signing material",
    )
require(
    "codestra.vicidial.recording.api.nonce" in controller, "nonce replay guard missing"
)
require(
    "UNIQUE(environment,service_identity,nonce)" in model, "nonce uniqueness missing"
)
required_upsert_fields = {
    "contract_version",
    "environment",
    "recording_uid",
    "vicidial_recording_id",
    "vicidial_call_id",
    "asterisk_uniqueid",
    "campaign_key",
    "agent_key",
    "started_at",
    "duration_seconds",
    "format",
    "codec",
    "channels",
    "sample_rate_hz",
    "file_size_bytes",
    "sha256",
    "object_version_id",
    "storage_status",
    "retention_class",
    "retention_until",
    "legal_hold",
}
required_literal = ast.literal_eval(
    controller.split("REQUIRED_FIELDS = ", 1)[1].split("\nSTATUS_FIELDS", 1)[0]
)
require(
    required_literal == required_upsert_fields,
    "canonical middleware upsert required fields drifted",
)
for mapping_field in ("campaign_key", "agent_key"):
    require(
        f'"{mapping_field}"' in controller,
        f"canonical mapping field missing: {mapping_field}",
    )
require(
    'payload["campaign_key"]' in controller
    and "call.campaign_id.campaign_id" in controller,
    "campaign mapping mismatch must fail closed",
)
require(
    'payload["agent_key"]' in controller
    and "call.agent_id.vicidial_user" in controller,
    "agent mapping mismatch must fail closed",
)
require(
    "MAPPING_KEY_RE.fullmatch(campaign_key)" in service_auth
    and "MAPPING_KEY_RE.fullmatch(agent_key)" in service_auth,
    "campaign and agent key schema validation missing",
)
require(
    "recording.call_id != call" in controller
    and "recording.campaign_id != call.campaign_id" in controller
    and "recording.agent_id != call.agent_id" in controller,
    "existing recording call mapping mismatch must fail closed",
)
for route in (
    "/codestra/api/v1/recordings/upsert",
    "/codestra/api/v1/recordings/<string:recording_uid>",
    "/codestra/api/v1/recordings/<string:recording_uid>/status",
):
    require(route in controller, f"internal route missing: {route}")
for response_field in (
    "contract_version",
    "recording_uid",
    "odoo_record_id",
    "call_link_status",
    "lead_link_status",
    "campaign_link_status",
    "agent_link_status",
    "storage_status",
    "retention_class",
    "retention_until",
    "legal_hold",
    "updated_at",
):
    require(f'"{response_field}"' in controller, f"ack field missing: {response_field}")
require(
    '"acknowledged"' not in controller, "noncanonical acknowledged boolean prohibited"
)
require("crm.lead" not in controller, "API must never create CRM leads")
require(".message_post(" not in model, "chatter delivery is prohibited")
require(
    "localStorage" in javascript and "localStorage." not in javascript,
    "URL persistence prohibited",
)
for forbidden in (
    "mail.activity",
    "calendar.event",
    "appointment",
    "sms.sms",
    "crm.lead.create",
    "n8n",
):
    require(forbidden not in controller.lower(), f"prohibited API action: {forbidden}")

print("recording module source gates: PASS")
