from __future__ import annotations

import copy
import contextlib
import hashlib
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from unittest import mock
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
# These are deliberately unsigned unit fixtures, never release evidence. Positive
# orchestration tests mock the external verifier, whose rejection is tested below.
SPEC = importlib.util.spec_from_file_location("production_validator", VALIDATOR)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


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
        stdout, stderr = io.StringIO(), io.StringIO()
        args = ["--file", self._relative(self.evidence_path), *extra]
        response = subprocess.CompletedProcess(
            [], 0, json.dumps([{"verificationResult": {"statement": {}}}]), ""
        )
        with (
            mock.patch.object(validator.subprocess, "run", return_value=response) as verify,
            contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr),
        ):
            code = validator.main(args)
        self.verifier_calls = verify.call_args_list
        return subprocess.CompletedProcess(args, code, stdout.getvalue(), stderr.getvalue())

    def _assert_rejected(self, expected: str) -> None:
        self._write_evidence()
        result = self._run()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(expected, result.stderr)

    def test_candidate_requires_both_cryptographic_verifications(self) -> None:
        result = self._run()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SIGNED_CANDIDATE_BINDING=PASS", result.stdout)
        self.assertEqual(len(self.verifier_calls), 2)
        for call, bundle, predicate in zip(
            self.verifier_calls, (self.provenance, self.sbom),
            ("https://slsa.dev/provenance/v1", "https://spdx.dev/Document"),
        ):
            command = call.args[0]
            self.assertEqual(command[:4], [
                "gh", "attestation", "verify", f"oci://{EXPECTED_IMAGE}@{IMAGE_DIGEST}",
            ])
            expected = {
                "--bundle": str(bundle), "--repo": "appolon1908-hue/Odoo",
                "--source-digest": SOURCE_SHA, "--signer-digest": SOURCE_SHA,
                "--source-ref": "refs/heads/main", "--predicate-type": predicate,
                "--cert-oidc-issuer": "https://token.actions.githubusercontent.com",
                "--cert-identity": "https://github.com/appolon1908-hue/Odoo/.github/workflows/cc-release-candidate.yml@refs/heads/main",
            }
            for flag, value in expected.items():
                self.assertEqual(command[command.index(flag) + 1], value)
            self.assertIn("--deny-self-hosted-runners", command)
            # gh rejects multiple identity selectors; the exact SAN above pins
            # both the signer workflow path and its protected main ref.
            self.assertNotIn("--signer-workflow", command)
            self.assertNotIn("--cert-identity-regex", command)
            self.assertEqual(call.kwargs["timeout"], 120)
            self.assertNotIn("shell", call.kwargs)

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

    def test_self_reported_signature_flags_cannot_override_verifier_failure(self) -> None:
        for kind in ("provenance", "sbom"):
            with self.subTest(kind=kind):
                failure = subprocess.CompletedProcess([], 1, "", "sensitive verifier detail")
                success = subprocess.CompletedProcess([], 0, '[{"verificationResult":{"statement":{}}}]', "")
                responses = [failure, success] if kind == "provenance" else [success, failure]
                errors: list[str] = []
                with mock.patch.object(validator.subprocess, "run", side_effect=responses):
                    validator.validate_candidate_binding(self.document, SOURCE_SHA, IMAGE_DIGEST, errors)
                self.assertIn(f"candidate.{kind} cryptographic attestation verification failed", errors)
                self.assertNotIn("sensitive verifier detail", " ".join(errors))

    def test_unavailable_timeout_or_empty_verifier_fails_closed(self) -> None:
        for failure in (FileNotFoundError(), subprocess.TimeoutExpired("gh", 120)):
            errors: list[str] = []
            with mock.patch.object(validator.subprocess, "run", side_effect=failure):
                validator.verify_attestation(self.provenance, "provenance", SOURCE_SHA, IMAGE_DIGEST, errors)
            self.assertTrue(errors)
        for output in ("[]", "{}", "not json", '[{"verificationResult":null}]'):
            errors = []
            with mock.patch.object(validator.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, output, "")):
                validator.verify_attestation(self.provenance, "provenance", SOURCE_SHA, IMAGE_DIGEST, errors)
            self.assertTrue(errors)

    def test_checksum_failure_never_reaches_cryptographic_verifier(self) -> None:
        self.provenance.write_text("{}\n", encoding="utf-8")
        self._assert_rejected("candidate checksum mismatch")
        self.assertEqual(self.verifier_calls, [])

    def test_duplicate_keys_are_rejected_in_evidence_and_manifest(self) -> None:
        for target in (self.evidence_path, self.manifest):
            with self.subTest(target=target.name):
                original = target.read_text(encoding="utf-8")
                target.write_text(original.replace('{', '{"schema_version":0,', 1), encoding="utf-8")
                if target == self.manifest:
                    self._write_checksums()
                result = self._run()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("duplicate JSON object key", result.stderr)
                self.assertEqual(self.verifier_calls, [])
                target.write_text(original, encoding="utf-8")
        self._write_checksums()

    def test_nonfinite_durations_cannot_satisfy_certification(self) -> None:
        for number in (float("nan"), float("inf"), -float("inf")):
            self.document["canary"]["duration_minutes"] = number
            self._assert_rejected("non-finite JSON number")
        self.document = self._valid_document()
        self._write_evidence()
        text = self.evidence_path.read_text(encoding="utf-8").replace('"duration_minutes": 15', '"duration_minutes": 1e999')
        self.evidence_path.write_text(text, encoding="utf-8")
        result = self._run()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("canary.duration_minutes must be a positive number", result.stderr)

    def test_boolean_counters_and_placeholder_backups_are_rejected(self) -> None:
        self.document["integration"]["unexpected_external_effects"] = False
        self._assert_rejected("integration.unexpected_external_effects must be 0")
        self.document = self._valid_document()
        self.document["backup"]["database_sha256"] = "0" * 64
        self._assert_rejected("backup.database_sha256 must be a non-zero")
        self.document = self._valid_document()
        self.document["backup"]["paired_backup_completed_at"] = "2026-02-31T12:00:00Z"
        self._assert_rejected("backup.paired_backup_completed_at must be a valid UTC timestamp")

    def test_github_login_case_does_not_allow_self_approval(self) -> None:
        self.document["activation_approval"]["approver"] = "CANDIDATE-BUILDER"
        self._assert_rejected("activation approval must be independent")

    def test_wrong_identity_types_report_errors_without_assertions(self) -> None:
        for key, value in (("source_sha", None), ("verdict", []), ("environment", {})):
            self.document = self._valid_document()
            self.document[key] = value
            self._write_evidence()
            result = self._run()
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.verifier_calls, [])

    def test_blocked_template_needs_no_registry_or_verifier(self) -> None:
        self.document = json.loads((ROOT / "release/production-evidence-template.json").read_text())
        self._write_evidence()
        result = self._run("--allow-blocked-template")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.verifier_calls, [])
        self.assertIn("SIGNED_CANDIDATE_BINDING=BLOCKED", result.stdout)

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
        signed = text.index("Create signed SBOM attestation")
        verified = text.index("Cryptographically verify published candidate attestations")
        finalized = text.index("Finalize production-candidate evidence")
        self.assertLess(signed, verified)
        self.assertLess(verified, finalized)


if __name__ == "__main__":
    unittest.main()
