import hashlib
import hmac
import importlib.util
import json
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


auth = load("lead_auth", ROOT / "controllers" / "service_auth.py")
contract = load("lead_contract", ROOT / "controllers" / "contract.py")
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
SECRET = b"synthetic-runtime-secret"


def payload():
    return {
        "contract_version": "1.1",
        "automation_event_id": "LAE-synthetic01",
        "idempotency_key": "a" * 64,
        "environment": "staging",
        "company_key": "COMPANY-1",
        "business_unit_key": "web-mobile-ai",
        "campaign_key": "TEST_LEADS",
        "automation_action": "UPDATE_ALLOWLISTED_FIELDS",
        "policy_version": "1.0",
        "correlation_id": "00000000-0000-4000-8000-000000000001",
        "attributes_schema_key": "web-mobile-ai-lead-v1",
        "attributes": {"solution_type": "AI"},
        "consent_snapshot": {
            "consent_status": "granted",
            "consent_purpose": "LEAD_SERVICE",
            "consent_source": "odoo",
            "consent_updated_at": "2026-01-01T00:00:00Z",
            "dnc_status": False,
            "dnc_updated_at": "2026-01-01T00:00:00Z",
            "jurisdiction": "DO",
            "source_system": "odoo",
        },
        "workflow_execution_id": "N8N-synthetic01",
        "result_code": "UPDATED",
        "lead_uid": "LEAD-synthetic01",
    }


def raw_body(value=None):
    return json.dumps(value or payload(), sort_keys=True, separators=(",", ":")).encode()


def headers(body, **changes):
    timestamp = NOW.isoformat()
    nonce = "synthetic-nonce"
    idem = "a" * 64
    digest = hashlib.sha256(body).hexdigest()
    material = auth.signing_material(
        auth.SIGNATURE_VERSION,
        auth.HTTP_METHOD,
        auth.REQUEST_PATH,
        timestamp,
        nonce,
        auth.IDENTITY,
        auth.AUDIENCE,
        "staging",
        auth.SCOPE,
        idem,
        digest,
    )
    value = {
        "X-Codestra-Signature-Version": auth.SIGNATURE_VERSION,
        "X-Service-Identity": auth.IDENTITY,
        "X-Service-Audience": auth.AUDIENCE,
        "X-Codestra-Timestamp": timestamp,
        "X-Codestra-Nonce": nonce,
        "X-Codestra-Content-SHA256": digest,
        "X-Codestra-Signature": hmac.new(SECRET, material, hashlib.sha256).hexdigest(),
        "Idempotency-Key": idem,
        "X-Codestra-Environment": "staging",
        "X-Codestra-Scope": auth.SCOPE,
    }
    value.update(changes)
    return value


def verify(original_body, supplied_headers, **changes):
    values = {
        "method": auth.HTTP_METHOD,
        "path": auth.REQUEST_PATH,
        "query_string": b"",
        "body": original_body,
        "headers": supplied_headers,
        "secret": SECRET,
        "expected_environment": "staging",
        "used_nonces": set(),
        "now": NOW,
    }
    values.update(changes)
    return auth.verify(**values)


class AuthAndContractTest(unittest.TestCase):
    def test_valid_signature_and_contract(self):
        body = raw_body()
        self.assertEqual(verify(body, headers(body)), "a" * 64)
        contract.validate_apply(payload())

    def test_method_path_body_and_header_tampering(self):
        body = raw_body()
        signed = headers(body)
        for key, replacement in (
            ("method", "PUT"),
            ("path", "/wrong"),
            ("body", b"{}"),
        ):
            with self.assertRaises(auth.AuthenticationError):
                verify(body, signed, **{key: replacement})
        for key, replacement in (
            ("Idempotency-Key", "b" * 64),
            ("X-Codestra-Timestamp", (NOW + timedelta(seconds=1)).isoformat()),
            ("X-Codestra-Nonce", "other"),
            ("X-Service-Identity", "wrong"),
            ("X-Service-Audience", "wrong"),
            ("X-Codestra-Environment", "production"),
            ("X-Codestra-Signature-Version", "HMAC-V1"),
            ("X-Codestra-Scope", "lead-automation.results.write"),
            ("X-Codestra-Scope", "*"),
        ):
            changed = dict(signed, **{key: replacement})
            with self.assertRaises(auth.AuthenticationError):
                verify(body, changed)

    def test_missing_version_scope_and_query_are_rejected(self):
        body = raw_body()
        for header in ("X-Codestra-Signature-Version", "X-Codestra-Scope"):
            changed = headers(body)
            changed.pop(header)
            with self.assertRaises(auth.AuthenticationError):
                verify(body, changed)
        with self.assertRaises(auth.AuthenticationError):
            verify(body, headers(body), query_string=b"unexpected=true")
        for ambiguous_path in (
            auth.REQUEST_PATH + "/",
            auth.REQUEST_PATH.replace("/automation/", "//automation/"),
            "/codestra/api/v1/leads/automation/%61pply",
        ):
            with self.assertRaises(auth.AuthenticationError):
                verify(body, headers(body), path=ambiguous_path)

    def test_authentication_precedes_persistent_nonce_and_model_mutation(self):
        controller = (ROOT / "controllers" / "lead_automation_api.py").read_text()
        verified = controller.index("idem = verify(")
        nonce_write = controller.index('automation.nonce"].consume(')
        receipt_access = controller.index("codestra.lead.automation.receipt")
        apply_authorized = controller.index(".apply_authorized(")
        self.assertLess(verified, nonce_write)
        self.assertLess(verified, receipt_access)
        self.assertLess(verified, apply_authorized)

    def test_expired_and_reused_nonce(self):
        body = raw_body()
        signed = headers(body)
        used = set()
        verify(body, signed, used_nonces=used)
        with self.assertRaises(auth.AuthenticationError):
            verify(body, signed, used_nonces=used)
        with self.assertRaises(auth.AuthenticationError):
            verify(body, signed, now=NOW + timedelta(minutes=6))

    def test_schema_rejects_missing_extra_action_and_pii(self):
        cases = []
        missing = payload()
        missing.pop("campaign_key")
        cases.append(missing)
        cases.append(dict(payload(), unknown=True))
        cases.append(dict(payload(), automation_action="SEND_EMAIL"))
        for field in ("phone_number", "email_address", "customer_name", "notes"):
            changed = deepcopy(payload())
            changed["attributes"] = {field: "synthetic"}
            cases.append(changed)
        for value in cases:
            with self.assertRaises(contract.ContractError):
                contract.validate_apply(value)

    def test_all_ack_results_and_unknown_rejection(self):
        for result in contract.ACK_RESULTS:
            value = {
                "contract_version": "1.1",
                "automation_event_id": "LAE-synthetic01",
                "automation_action": "UPDATE_ALLOWLISTED_FIELDS",
                "lead_uid": "LEAD-synthetic01",
                "odoo_record_id": 42,
                "result": result,
                "applied_fields": [],
                "unchanged_fields": [],
                "rejected_fields": [],
                "company_key": "COMPANY-1",
                "business_unit_key": "web-mobile-ai",
                "campaign_key": "TEST_LEADS",
                "policy_version": "1.0",
                "updated_at": "2026-01-01T00:00:01Z",
                "idempotent_replay": False,
            }
            if result == "FAILED":
                value["result_code"] = "PERMANENT_FAILURE"
            contract.validate_ack(value, payload())
        value["result"] = "UNKNOWN"
        with self.assertRaises(contract.ContractError):
            contract.validate_ack(value, payload())


if __name__ == "__main__":
    unittest.main()
