from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "scripts" / "validate_production_evidence.py"
WORKFLOW = ROOT / ".github" / "workflows" / "cc-release-candidate.yml"
EXPECTED_IMAGE = "ghcr.io/appolon1908-hue/odoo"
SOURCE_SHA = "a" * 40
IMAGE_DIGEST = "sha256:" + "b" * 64
SIGSTORE_BUNDLE = {
    "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json",
    "verificationMaterial": {"tlogEntries": [{}]},
    "dsseEnvelope": {
        "payloadType": "application/vnd.in-toto+json",
        "payload": "e30=",
        "signatures": [{"sig": "AA=="}],
    },
}


class ProductionEvidenceControlsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(
            prefix=".production-evidence-", dir=ROOT / "tests"
        )
        self.directory = Path(self.temp.name)
        self.provenance = self.directory / "candidate.provenance.sigstore.json"
        self.sbom = self.directory / "candidate.sbom.sigstore.json"
        self.manifest = self.directory / "candidate.production-candidate.json"
        self.checksums = self.directory / "SHA256SUMS"
        self.evidence_path = self.directory / "production-evidence.json"

        for path in (self.provenance, self.sbom):
            path.write_text(json.dumps(SIGSTORE_BUNDLE) + "\n", encoding="utf-8")
        self.manifest.write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "release_type": "signed-oci-production-candidate",
                    "source_repository": "appolon1908-hue/Odoo",
                    "source_sha": SOURCE_SHA,
                    "source_commit_verified_signature": True,
                    "artifact_ready": True,
                    "image": {
                        "name": EXPECTED_IMAGE,
                        "digest": IMAGE_DIGEST,
                    },
                    "attestations": {
                        "provenance": "https://github.com/appolon1908-hue/Odoo/attestations/1",
                        "sbom": "https://github.com/appolon1908-hue/Odoo/attestations/2",
                    },
                    "safety": {
                        "production_deployed": False,
                        "database_migrated": False,
                        "live_odoo_write_enabled": False,
                        "external_delivery_enabled": False,
                        "email_delivery_enabled": False,
                        "sms_delivery_enabled": False,
                        "pstn_dialing_enabled": False,
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        self._write_checksums()
        self.document = self._valid_document()
        self._write_evidence()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _relative(self, path: Path) -> str:
        return path.relative_to(ROOT).as_posix()

    def _write_checksums(self) -> None:
        lines = []
        for path in sorted((self.manifest, self.provenance, self.sbom)):
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest}  {path.name}")
        self.checksums.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _valid_document(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "release_id": "odoo-production-candidate-test",
            "source_sha": SOURCE_SHA,
            "image": {"name": EXPECTED_IMAGE, "digest": IMAGE_DIGEST},
            "candidate": {
                "manifest_path": self._relative(self.manifest),
                "checksums_path": self._relative(self.checksums),
                "provenance_bundle_path": self._relative(self.provenance),
                "sbom_bundle_path": self._relative(self.sbom),
                "provenance_verified": True,
                "sbom_verified": True,
            },
            "environment": "production",
            "runtime_flags": {
                "LIVE_ODOO_WRITE": False,
                "ENABLE_EXTERNAL_DELIVERY": False,
                "EMAIL_DELIVERY": False,
                "SMS_DELIVERY": False,
                "CALLBACK_DISPATCH": False,
                "PSTN_DIALING": False,
                "N8N_ACTIVATION": False,
                "VICIDIAL_LIVE_CONTROL": False,
            },
            "approved_live_capabilities": [],
            "source_authority": {
                "server_matches_source_sha": True,
                "server_matches_image_digest": True,
                "mutable_host_checkout_removed": True,
            },
            "backup": {
                "database_sha256": "c" * 64,
                "filestore_sha256": "d" * 64,
                "paired_backup_completed_at": "2026-09-03T12:00:00Z",
                "off_host_copy_verified": True,
            },
            "migration": {
                "affected_modules": [],
                "upgrade_passed": True,
                "interrupted_restart_passed": True,
                "schema_audit_passed": True,
            },
            "restore": {
                "database_restored": True,
                "filestore_restored": True,
                "checksums_verified": True,
                "rto_seconds": 120,
            },
            "integration": {
                "caddy_passed": True,
                "kong_passed": True,
                "middleware_passed": True,
                "odoo_passed": True,
                "idempotency_passed": True,
                "tenant_isolation_passed": True,
                "negative_authorization_passed": True,
                "unexpected_external_effects": 0,
            },
            "rollback": {
                "rehearsed": True,
                "source_restored": True,
                "database_restored": True,
                "filestore_restored": True,
                "post_rollback_smoke_passed": True,
            },
            "canary": {
                "mode": "read-only",
                "passed": True,
                "duration_minutes": 15,
                "error_rate": 0,
                "unexpected_writes": 0,
            },
            "soak": {
                "passed": True,
                "duration_minutes": 60,
                "error_rate": 0,
                "reconciliation_backlog": 0,
            },
            "activation_approval": {
                "approved": True,
                "approver": "independent-release-owner",
                "candidate_author": "candidate-builder",
                "review_state": "APPROVED",
                "review_url": "https://github.com/appolon1908-hue/Odoo/pull/61#pullrequestreview-1",
                "approved_at": "2026-09-03T12:30:00Z",
                "source_sha": SOURCE_SHA,
                "image_digest": IMAGE_DIGEST,
                "provenance": "github-protected-review",
            },
            "verdict": "PRODUCTION_CERTIFIED",
        }

    def _write_evidence(self) -> None:
        self.evidence_path.write_text(
            json.dumps(self.document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _run(self, *extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(VALIDATOR),
                "--file",
                self._relative(self.evidence_path),
                *extra,
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def _assert_rejected(self, expected: str) -> None:
        self._write_evidence()
        result = self._run()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(expected, result.stderr)

    def test_valid_production_evidence_is_bound_to_signed_candidate(self) -> None:
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SIGNED_CANDIDATE_BINDING=PASS", result.stdout)

    def test_zero_source_sha_is_rejected_outside_blocked_template(self) -> None:
        self.document["source_sha"] = "0" * 40
        self._assert_rejected("source_sha must be a non-zero")

    def test_every_live_effect_flag_is_rejected_for_read_only_canary(self) -> None:
        for flag in tuple(self.document["runtime_flags"]):
            with self.subTest(flag=flag):
                candidate = copy.deepcopy(self.document)
                candidate["verdict"] = "PRODUCTION_READ_ONLY_CANARY_CERTIFIED"
                candidate["environment"] = "production-read-only-canary"
                candidate["runtime_flags"][flag] = True
                candidate["approved_live_capabilities"] = [flag]
                self.document = candidate
                self._assert_rejected(
                    "read-only canary requires every live-effect flag false"
                )
                self.document = self._valid_document()

    def test_candidate_manifest_identity_mismatch_is_rejected(self) -> None:
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        manifest["source_sha"] = "e" * 40
        self.manifest.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        self._write_checksums()
        self._assert_rejected("candidate manifest source_sha does not match evidence")

    def test_checksum_mismatch_is_rejected(self) -> None:
        self.manifest.write_text("{}\n", encoding="utf-8")
        self._assert_rejected("candidate checksum mismatch")

    def test_unsigned_bundle_is_rejected(self) -> None:
        self.provenance.write_text("{}\n", encoding="utf-8")
        self._write_checksums()
        self._assert_rejected(
            "candidate.provenance_bundle_path does not contain signed attestation material"
        )

    def test_negative_authorization_gate_is_required(self) -> None:
        self.document["integration"]["negative_authorization_passed"] = False
        self._assert_rejected(
            "integration.negative_authorization_passed must be true"
        )

    def test_zero_canary_duration_is_rejected(self) -> None:
        self.document["canary"]["duration_minutes"] = 0
        self._assert_rejected("canary.duration_minutes must be a positive number")

    def test_zero_soak_duration_is_rejected(self) -> None:
        self.document["soak"]["duration_minutes"] = 0
        self._assert_rejected("soak.duration_minutes must be a positive number")

    def test_self_approval_is_rejected(self) -> None:
        self.document["activation_approval"]["approver"] = "candidate-builder"
        self._assert_rejected(
            "activation approval must be independent of the candidate author"
        )

    def test_release_workflow_uses_single_installer_and_runtime_gate(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("${{ github.ref_name }}", text)
        self.assertIn('test "$GITHUB_REF_NAME" = "main"', text)
        self.assertIn("bash scripts/install_trivy.sh", text)
        self.assertNotIn("TRIVY_ARCHIVE_SHA256:", text)
        source = text.index("Run exact-main source validation")
        runtime = text.index("Test Odoo 19 and PostgreSQL runtime")
        build = text.index("Build deterministic source evidence")
        self.assertLess(source, runtime)
        self.assertLess(runtime, build)


if __name__ == "__main__":
    unittest.main()
