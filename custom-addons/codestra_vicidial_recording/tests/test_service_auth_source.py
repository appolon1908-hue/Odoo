import importlib.util
import time
import unittest
from pathlib import Path

AUTH_PATH = Path(__file__).resolve().parents[1] / "controllers" / "service_auth.py"
SPEC = importlib.util.spec_from_file_location("recording_service_auth", AUTH_PATH)
AUTH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUTH)


class TestServiceAuthentication(unittest.TestCase):
    def setUp(self):
        self.signing_key = bytes(range(32)).hex()
        self.body = b'{"contract_version":"1.0"}'
        self.now = int(time.time())
        self.idempotency_key = "idempotency-" + ("0" * 16)
        self.headers = {
            "X-Service-Identity": "codestra-middleware",
            "X-Service-Audience": "codestra-odoo-recording-api",
            "X-Codestra-Timestamp": str(self.now),
            "X-Codestra-Nonce": "synthetic-nonce-0001",
            "X-Codestra-Content-SHA256": AUTH.content_sha256(self.body),
            "Idempotency-Key": self.idempotency_key,
            "X-Codestra-Environment": "staging",
        }
        self.headers["X-Codestra-Signature"] = AUTH.signature(
            self.signing_key,
            timestamp=self.headers["X-Codestra-Timestamp"],
            nonce=self.headers["X-Codestra-Nonce"],
            method="POST",
            path="/codestra/api/v1/recordings/upsert",
            idempotency_key=self.headers["Idempotency-Key"],
            body_hash=self.headers["X-Codestra-Content-SHA256"],
        )

    def validate(self, headers=None, body=None):
        return AUTH.validate_request(
            self.headers if headers is None else headers,
            self.body if body is None else body,
            "POST",
            "/codestra/api/v1/recordings/upsert",
            self.signing_key,
            "codestra-middleware",
            "codestra-odoo-recording-api",
            "staging",
            now=self.now,
        )

    def test_valid_hmac_contract(self):
        result = self.validate()
        self.assertEqual(result["environment"], "staging")
        self.assertEqual(result["nonce"], "synthetic-nonce-0001")
        canonical = "\n".join(
            (
                "POST",
                "/codestra/api/v1/recordings/upsert",
                self.headers["X-Codestra-Timestamp"],
                self.headers["X-Codestra-Nonce"],
                self.headers["Idempotency-Key"],
                self.headers["X-Codestra-Content-SHA256"],
            )
        ).encode()
        self.assertEqual(
            AUTH.signing_material(
                timestamp=self.headers["X-Codestra-Timestamp"],
                nonce=self.headers["X-Codestra-Nonce"],
                method="POST",
                path="/codestra/api/v1/recordings/upsert",
                idempotency_key=self.headers["Idempotency-Key"],
                body_hash=self.headers["X-Codestra-Content-SHA256"],
            ),
            canonical,
        )

    def test_missing_and_invalid_signature_rejected(self):
        for value in (None, "0" * 64):
            headers = dict(self.headers)
            if value is None:
                headers.pop("X-Codestra-Signature")
            else:
                headers["X-Codestra-Signature"] = value
            with self.assertRaises(ValueError):
                self.validate(headers)

    def test_expired_timestamp_rejected(self):
        headers = dict(self.headers)
        headers["X-Codestra-Timestamp"] = str(self.now - 301)
        with self.assertRaises(ValueError):
            self.validate(headers)

    def test_identity_audience_environment_and_body_hash_rejected(self):
        mutations = (
            ("X-Service-Identity", "wrong"),
            ("X-Service-Audience", "wrong"),
            ("X-Codestra-Environment", "production"),
            ("X-Codestra-Content-SHA256", "0" * 64),
        )
        for name, value in mutations:
            headers = dict(self.headers)
            headers[name] = value
            with self.assertRaises(ValueError):
                self.validate(headers)
        with self.assertRaises(ValueError):
            self.validate(body=b"changed")

    def test_mapping_mismatch_fails_closed(self):
        AUTH.validate_call_mapping(
            "SYNTHETIC", "synthetic-agent", "SYNTHETIC", "synthetic-agent"
        )
        for values in (
            ("wrong", "synthetic-agent", "SYNTHETIC", "synthetic-agent"),
            ("SYNTHETIC", "wrong", "SYNTHETIC", "synthetic-agent"),
            ("SYNTHETIC", "synthetic-agent", "", "synthetic-agent"),
            ("SYNTHETIC", "synthetic-agent", "SYNTHETIC", ""),
            ("INVALID KEY", "synthetic-agent", "INVALID KEY", "synthetic-agent"),
            ("SYNTHETIC", "invalid/agent", "SYNTHETIC", "invalid/agent"),
            ("x" * 65, "synthetic-agent", "x" * 65, "synthetic-agent"),
            ("SYNTHETIC", "x" * 65, "SYNTHETIC", "x" * 65),
        ):
            with self.assertRaises(ValueError):
                AUTH.validate_call_mapping(*values)


if __name__ == "__main__":
    unittest.main()
